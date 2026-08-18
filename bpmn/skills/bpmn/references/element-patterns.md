# BPMN semantic-XML patterns

Copy-paste patterns for authoring the **semantic-only** `.bpmn` file. Never write
`<bpmndi:...>` sections — `layout.mjs` generates them. Everything here is the
bpmn.io-compatible core subset; exotic elements (choreography, conversation,
complex gateway) are out of scope.

## File skeleton

```xml
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    id="Defs_<Name>" targetNamespace="http://bpmn.io/schema/bpmn">
  <!-- process or collaboration+processes here -->
</bpmn:definitions>
```

## Non-negotiable mechanics

- **Every flow node lists its `<bpmn:incoming>` / `<bpmn:outgoing>` flow ids** —
  bpmn-auto-layout traverses these; missing ones produce broken layouts.
- **IDs are stable and human-readable**: `Task_ReviewOrder`, `Gateway_IsApproved`,
  `Flow_Approved`, `Start_OrderReceived`, `End_Merged`, `Pool_OrderService`,
  `Lane_Reviewer`. Never rename an id during iteration unless the element's
  meaning changed — stable ids keep edits surgical.
- One element = one XML block; sequence flows go **after** the flow nodes.

## Events

```xml
<bpmn:startEvent id="Start_X" name="Order received">
  <bpmn:outgoing>Flow_1</bpmn:outgoing>
</bpmn:startEvent>

<!-- typed start: message / timer -->
<bpmn:startEvent id="Start_Msg" name="Request received">
  <bpmn:outgoing>Flow_1</bpmn:outgoing>
  <bpmn:messageEventDefinition />
</bpmn:startEvent>
<bpmn:startEvent id="Start_Cron" name="Every Monday 09:00">
  <bpmn:outgoing>Flow_1</bpmn:outgoing>
  <bpmn:timerEventDefinition />
</bpmn:startEvent>

<bpmn:endEvent id="End_X" name="Order settled">
  <bpmn:incoming>Flow_9</bpmn:incoming>
</bpmn:endEvent>
<!-- typed ends: <bpmn:messageEventDefinition/>, <bpmn:errorEventDefinition/>,
     <bpmn:terminateEventDefinition/> inside the endEvent -->

<!-- intermediate catch (wait) / throw (emit) -->
<bpmn:intermediateCatchEvent id="Catch_Reply" name="Reply received">
  <bpmn:incoming>Flow_3</bpmn:incoming>
  <bpmn:outgoing>Flow_4</bpmn:outgoing>
  <bpmn:messageEventDefinition />
</bpmn:intermediateCatchEvent>
<bpmn:intermediateThrowEvent id="Throw_Notify" name="Notify requester">
  <bpmn:incoming>Flow_4</bpmn:incoming>
  <bpmn:outgoing>Flow_5</bpmn:outgoing>
  <bpmn:messageEventDefinition />
</bpmn:intermediateThrowEvent>
```

## Tasks

`bpmn:task` is the generic box. Typed variants render a small icon and add
meaning — prefer them when the actor kind is known:

| Element                 | Use for                                    |
| ----------------------- | ------------------------------------------ |
| `bpmn:userTask`         | human does it in a UI                      |
| `bpmn:serviceTask`      | automated / system call                    |
| `bpmn:sendTask`         | sends a message to another pool            |
| `bpmn:receiveTask`      | waits for a message                        |
| `bpmn:manualTask`       | human, outside any system                  |
| `bpmn:scriptTask`       | inline automation / job                    |
| `bpmn:businessRuleTask` | decision table / rules engine              |

```xml
<bpmn:userTask id="Task_ReviewOrder" name="Review order">
  <bpmn:incoming>Flow_2</bpmn:incoming>
  <bpmn:outgoing>Flow_3</bpmn:outgoing>
</bpmn:userTask>
```

## Gateways

```xml
<!-- exclusive split: label the gateway as a question, label EVERY outgoing flow.
     Do NOT set default="..." on descriptive diagrams — it makes bpmnlint demand
     conditionExpressions on every sibling flow (conditional-flows rule).
     default + conditions belong to executable models only. -->
<bpmn:exclusiveGateway id="Gateway_IsApproved" name="Approved?">
  <bpmn:incoming>Flow_3</bpmn:incoming>
  <bpmn:outgoing>Flow_Yes</bpmn:outgoing>
  <bpmn:outgoing>Flow_No</bpmn:outgoing>
</bpmn:exclusiveGateway>
<bpmn:sequenceFlow id="Flow_Yes" name="yes" sourceRef="Gateway_IsApproved" targetRef="Task_A" />
<bpmn:sequenceFlow id="Flow_No"  name="no"  sourceRef="Gateway_IsApproved" targetRef="Task_B" />

<!-- exclusive join: same element, multiple incoming, one outgoing, usually no name -->
<bpmn:exclusiveGateway id="Gateway_Join_1">
  <bpmn:incoming>Flow_A</bpmn:incoming>
  <bpmn:incoming>Flow_B</bpmn:incoming>
  <bpmn:outgoing>Flow_Next</bpmn:outgoing>
</bpmn:exclusiveGateway>
```

- `bpmn:parallelGateway` — AND split/join (all branches run; join waits for all).
- `bpmn:inclusiveGateway` — OR (one or more branches).
- `bpmn:eventBasedGateway` — "whichever event happens first"; outgoing flows must
  target intermediate catch events or receive tasks.

**Every split needs a matching join** of the same kind before flows re-merge —
merging two flows straight into a task triggers the `fake-join` lint warning.

## Boundary events (exceptions on a task)

```xml
<bpmn:boundaryEvent id="Boundary_Timeout" name="48h elapsed" attachedToRef="Task_ReviewOrder">
  <bpmn:outgoing>Flow_Escalate</bpmn:outgoing>
  <bpmn:timerEventDefinition />
</bpmn:boundaryEvent>
<!-- error: <bpmn:errorEventDefinition/>; message: <bpmn:messageEventDefinition/>
     non-interrupting: add cancelActivity="false" -->
```

Boundary events do **not** appear in lane `flowNodeRef` lists — they follow
their host task automatically.

## Lanes (roles inside ONE organization)

```xml
<bpmn:process id="Process_X" isExecutable="false">
  <bpmn:laneSet id="LaneSet_1">
    <bpmn:lane id="Lane_Developer" name="Developer">
      <bpmn:flowNodeRef>Start_Ready</bpmn:flowNodeRef>
      <bpmn:flowNodeRef>Task_OpenMR</bpmn:flowNodeRef>
    </bpmn:lane>
    <bpmn:lane id="Lane_Reviewer" name="Reviewer">
      <bpmn:flowNodeRef>Task_Review</bpmn:flowNodeRef>
    </bpmn:lane>
  </bpmn:laneSet>
  <!-- flow nodes + sequence flows as usual -->
</bpmn:process>
```

Every flow node (except boundary events) must be referenced by exactly one lane.
Lane order in the XML = top-to-bottom order in the diagram — put the
process-driving role first.

## Collaboration (pools = separate organizations/systems)

```xml
<bpmn:collaboration id="Collab_1">
  <bpmn:participant id="Pool_Front" name="web-frontend" processRef="Process_Front" />
  <bpmn:participant id="Pool_Core"  name="order-service"        processRef="Process_Core" />
  <!-- black-box pool (no visible internals): omit processRef -->
  <bpmn:participant id="Pool_Customer" name="Customer" />
  <bpmn:messageFlow id="MF_Request" name="POST /orders"
      sourceRef="Task_Submit" targetRef="Start_Request" />
</bpmn:collaboration>
<!-- then one <bpmn:process> per non-black-box participant -->
```

- Message flow endpoints: tasks, events, or whole participants (for black-box).
- Pool order in the XML = top-to-bottom stacking. Put the initiating pool first
  and order pools so message flows go mostly between neighbours.
- **Sequence flow never crosses a pool boundary; message flow never stays inside
  one pool.**

## Subprocess

```xml
<bpmn:subProcess id="Sub_Escalation" name="Handle escalation">
  <bpmn:incoming>Flow_5</bpmn:incoming>
  <bpmn:outgoing>Flow_6</bpmn:outgoing>
  <bpmn:startEvent id="Start_Sub"> ... </bpmn:startEvent>
  <!-- inner flow nodes + sequence flows nested here -->
</bpmn:subProcess>
```

Known limitation: expanded subprocesses inside **lanes** or **pools** may need a
manual nudge in bpmn.io afterwards — the layout post-passes only move top-level
nodes. Plain single-process subprocesses lay out fine.

## Cross-diagram handoffs (process suites)

Sender ends with a **message end event**; receiver begins with a **message start
event**; names mirror each other:

```xml
<!-- planning.bpmn -->
<bpmn:endEvent id="End_ToExecution" name="Item ready (to Execution)">
  <bpmn:incoming>Flow_Exit</bpmn:incoming>
  <bpmn:messageEventDefinition id="MsgDef_ToExecution" />
</bpmn:endEvent>

<!-- execution.bpmn -->
<bpmn:startEvent id="Start_Pulled" name="Item pulled (from Planning)">
  <bpmn:outgoing>Flow_Pulled</bpmn:outgoing>
  <bpmn:messageEventDefinition id="MsgDef_Pulled" />
</bpmn:startEvent>
```

A process may have several message starts feeding different entry points, plus
at most one blank start (`single-blank-start-event` rule). **Never use link
events across files**: `bpmn:linkEventDefinition` is intra-process by spec and
bpmnlint errors on an unpaired link name (`link-event` rule). Use link
throw/catch pairs only as page-jump shortcuts within one large diagram.

## Annotations

```xml
<bpmn:textAnnotation id="Note_1">
  <bpmn:text>Only for orders above $10k</bpmn:text>
</bpmn:textAnnotation>
<bpmn:association id="Assoc_1" sourceRef="Task_ReviewOrder" targetRef="Note_1" />
```

Use sparingly — the layouter gives annotations rough placement at best. Prefer
encoding context in element names; reach for annotations only when a caveat
genuinely can't live in a name.
