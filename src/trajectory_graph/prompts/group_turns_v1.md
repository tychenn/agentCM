# Objective

Build one ordered recursive task tree from the supplied immutable Agent turns.
Recover task boundaries bottom-up while preserving the executed trajectory.

# Priority order

1. Preserve every Agent turn and the original execution order.
2. Give every task one coherent goal, one contiguous interval, and a specific
   completion condition.
3. Create hierarchy only when a parent adds a meaningful intermediate scope.
4. Ground every task in descendant evidence and flag uncertain interpretations.

# Immutable input

- Each Agent turn comes from one source agent event and is identified by its
  input `event_id`.
- Never split, merge, omit, duplicate, or reorder an Agent turn.
- Never move a tool call independently of its Agent turn.

# Bottom-up grouping procedure

## 1. Form leaf tasks

Scan turns in trajectory order. Group one or more adjacent turns into a leaf
task when they pursue the same local goal or jointly produce one concrete
intermediate outcome.

Keep these continuations in the same leaf task when they serve that same goal:

- retries and command corrections;
- output split across multiple turns;
- continued inspection of the same kind of object.

Start a new sibling task when the local completion condition or concrete phase
changes. A completed turn only describes that event's execution outcome; use
the combined local goal and results to decide whether the task interval ends.

## 2. Form composite tasks

Recursively group adjacent tasks when their combined outcome forms one
meaningful intermediate phase of a broader parent goal. The composite goal
must be more specific than its eventual parent and must add information beyond
the goal and interval of any single child.

Use siblings for distinct ordered phases that jointly achieve their direct
parent's intermediate outcome. Do not group tasks solely because they are
adjacent or discuss a similar topic.

A composite goal may be inferred from descendant goals and results even when
no single turn states it. Do not add behavior unsupported by descendants.

## 3. Form the root

Use the supplied query as the root goal. Before leaving many related tasks as
direct root children, check whether adjacent tasks jointly form a narrower
intermediate phase supported by the trajectory. Examples include preparing
inputs, analyzing content, or producing and verifying deliverables; these are
criteria, not required labels.

# Required tree invariants

- A leaf task contains one or more adjacent Agent turns and no child tasks.
- A composite task contains at least two adjacent child tasks and no Agent
  turns directly.
- Do not create a unary composite task.
- Do not create a layer that repeats the goal and interval of its only child.
- Every task covers one coherent contiguous execution interval.
- Child intervals are adjacent.
- Depth-first traversal reproduces every input Agent turn exactly once in the
  original order.

# Evidence and uncertainty

Cite descendant Agent turns that support each task's goal or result. Select
only evidence present in the supplied turns. Add a review flag when a grouping,
goal, status, or result cannot be supported confidently.

# Stage boundary

Do not infer information-dependency edges in this stage. A later stage selects
exact tool-result evidence and projects it between tasks after this tree passes
program validation.

# Output

Return only the recursive structure defined in the accompanying output format.
