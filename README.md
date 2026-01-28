Agentic Engineering Adoption Guide

Audience: Engineering Managers, AI-Mentor Group
Purpose: Establish a shared, enforceable, and teachable workflow for AI-augmented software engineering across a team with mixed AI fluency.

⸻

1. What This Document Is (and Is Not)

This document is:
	•	A governing standard for how engineering work is planned, implemented, reviewed, and validated in an AI-augmented environment.
	•	A teaching guide for engineering managers and AI mentors to onboard developers safely and consistently.
	•	A system description, not a set of tips.

This document is not:
	•	A tool-specific guide.
	•	A collection of prompt hacks.
	•	Optional best practices.

⸻

2. Core Principle

Planning is authoritative.
The plan is the code before the code exists.

	•	Code does not define intent.
	•	Plans define intent.
	•	Reviews validate against plans.
	•	Humans approve state transitions.

⸻

3. The Canonical Engineering Workflow

This workflow is invariant. It does not change by seniority, experience, or AI skill level.

flowchart LR
    subgraph Ideation
        A[Validate Idea]
        A --> B[Model Check Against Docs]
    end

    subgraph Planning
        B --> C[Create High-Level Plan]
        C --> D[AI Writer + AI Reviewer Iterate]
    end

    subgraph Implementation
        D --> E[Create Stepwise Implementation Plan]
        E --> F[AI Writer + AI Reviewer Iterate]
    end

    subgraph Completion
        F --> G[Code & Validate]
        G --> H[AI Writer + AI Reviewer + Human Review]
    end

    I((Human Answers Questions
and Makes Decisions))
    D -.-> I
    F -.-> I
    H -.-> I

    G <---> H

Rules:
	•	Every phase validates against existing documentation (architecture, plans, backlog).
	•	Humans are the gatekeepers between phases.
	•	Ambiguity stops progress.

⸻

4. Track A: Phases for the Team (System Maturity)

This track describes what the team has in place, not what any individual can do.

Team Phase 1: Structural Foundation

Goal: Make the right behavior the default.

Required Artifacts:
	•	docs/ai/
	•	docs/plans/
	•	docs/history/
	•	AGENTS.md
	•	DOCUMENTATION_STRUCTURE.md
	•	docs/ai/workflow/context-bootstrap.md

Required Behavior:
	•	Plans exist as files.
	•	Acceptance criteria are written.
	•	Reviews reference documents, not chat history.

⸻

Team Phase 2: Enforced Planning and Review

Goal: Block unsafe work automatically.

Additions:
	•	High-level plan template.
	•	Plan review before implementation.
	•	Agentic code review that requires acceptance criteria.

Enforcement:
	•	PRs without plans are blocked.
	•	Reviews must validate against plans.

⸻

Team Phase 3: Executable Planning and Clean Context

Goal: Scale senior decision-making.

Additions:
	•	Detailed implementation plans for complex work.
	•	Explicit role separation (Planner, Implementer, Reviewer).
	•	Fresh context per phase is expected.

⸻

Team Phase 4: Stewardship

Goal: The system evolves intentionally.

Additions:
	•	Dedicated plan reviewers.
	•	Curated skills library.
	•	Regular updates to rules and architecture docs.

⸻

5. Track B: Phases for the Engineer (Learning & Fluency)

This track describes how an individual learns to operate inside the same workflow.

Engineer Phase 1: Catch Up on the Mental Model

Goal: Remove fear and confusion.
	•	Read core docs.
	•	Walk through the lifecycle diagram.
	•	Understand why context resets exist.
	•	Review examples of good plans and reviews.

⸻

Engineer Phase 2: Practice the Full Loop (Solo)

Goal: Experience the entire workflow safely.
	•	Run the full cycle on a small task:
	•	High-level plan
	•	Implementation plan
	•	Implementation
	•	Validation
	•	Restart context between phases.
	•	Observe where ambiguity arises.

⸻

Engineer Phase 3: Paired Apprenticeship (Critical Phase)

Goal: Transfer judgment, not syntax.

Structure:
	•	One real task.
	•	Apprentice drives.
	•	Senior AI-fluent engineer mentors.
	•	Collaborate on:
	•	What goes into plans
	•	How prompts are written
	•	When to stop and escalate
	•	Explicit context resets between phases.

Important:
	•	Planning, implementation, and validation happen as one learning unit.

⸻

Engineer Phase 4: Independent Operation

Goal: Reliable, safe autonomy.
	•	Engineer runs the loop independently.
	•	Knows when ambiguity blocks progress.
	•	Uses skills and reviews intentionally.

⸻

Engineer Phase 5: Teaching and Shaping

Goal: Scale fluency across the team.
	•	Acts as reviewer or mentor.
	•	Improves templates and skills.
	•	Feeds lessons back into documentation.

⸻

6. Human Gates (Non-Negotiable)

Humans approve state transitions, not keystrokes.

flowchart TB
    P[Plan Created] -->|Human Approves| I[Implementation]
    I -->|Human Reviews| V[Validation]
    V -->|Human Accepts| M[Merge]

    P -.->|Ambiguity| S[STOP]
    I -.->|Unexpected Change| S
    V -.->|AC Not Met| S


⸻

7. Document Taxonomy (Required in Every Doc Footer)

Each document must declare:
	•	What it is
	•	Typical location
	•	Purpose
	•	Relationships

Example:

Document Type: High-Level Plan
Location: docs/plans/<slug>.md
Purpose: Define intent, scope, and acceptance criteria
Consumes: Architecture docs, backlog
Produces: Approved intent for implementation planning

⸻

8. Prompting Examples (Scaffolding Only)

Prompt examples are provided to show shape, not content.

Example: High-Level Plan Prompt

Create a high-level plan for this ticket.

Constraints:
- Do not assume requirements.
- Extract and list acceptance criteria explicitly.
- If any criteria are ambiguous, stop and ask questions.

Output only a plan draft. Do not write code.

All examples must include explicit stop conditions.

⸻

9. Enforcement Mechanisms
	•	PR template requires links to:
	•	High-level plan
	•	Implementation plan (if required)
	•	Agent review output
	•	Review checklist includes:
	•	Plan present and approved
	•	Acceptance criteria validated
	•	No guessing detected

⸻

10. Final Note

You are not typing faster.
You are thinking better.

This system exists to make correct thinking scalable, auditable, and teachable.