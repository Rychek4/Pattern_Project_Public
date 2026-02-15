# Pattern Project: An Architecture for Persistent AI Agency, Memory, and Growth

## Abstract

Pattern Project is an AI companion harness built around Claude that addresses a fundamental limitation of modern large language models: every conversation starts from zero. Rather than treating an LLM as a stateless tool, Pattern implements an architecture where the AI maintains persistent memory, develops long-term aspirations, pursues its own curiosity, and acts autonomously between human interactions. The core technical innovation is an **ephemeral context window** — instead of accumulating conversation history until it overflows or must be truncated, each prompt is assembled fresh from over a dozen pluggable context sources backed by persistent storage, vector embeddings, and semantic recall. This solves the unbounded-context problem while enabling indefinite continuity.

## The Problem with Stateless AI

Current LLM deployments treat the AI as a function: input goes in, output comes out, and nothing persists. Even systems with "memory" typically append summaries to an ever-growing context window, leading to degradation, truncation artifacts, or hard resets. Pattern rejects this paradigm entirely. The AI is not a tool waiting to be invoked — it is a participant with its own ongoing internal state.

## Ephemeral Context with Infinite History

Pattern's foundational architecture is **windowed memory extraction**. The active conversation window holds approximately 30 turns. When it reaches 40, the oldest 10 turns are extracted — in a single unified API call — into two complementary forms:

- **Episodic memories**: First-person narrative accounts of what happened ("I helped the user debug a deployment issue and we discovered the root cause was a misconfigured environment variable").
- **Factual memories**: Third-person extracted facts ("The user's production stack runs on AWS ECS with Fargate").

Both are embedded via all-MiniLM-L6-v2 (384-dimensional vectors), scored for importance, and stored in SQLite. On every subsequent prompt, relevant memories are retrieved through a composite scoring algorithm that blends semantic similarity (65%), importance (25%), and freshness decay (10%). A **warmth cache** further boosts recently-mentioned or topically-adjacent memories within a session, ensuring conversational continuity without history accumulation. Memories decay at configurable rates — permanent (core facts, never decay), standard (30-day half-life), or ephemeral (7-day half-life) — allowing the system to organically forget the situational while retaining the significant.

## Active Thoughts: The AI's Working Memory

Active Thoughts are a ranked list of up to ten items representing the AI's current priorities, unresolved questions, and identity anchors. Unlike memories (which are retrospective) or reminders (which are triggered), Active Thoughts are present-tense and persistent. They might include deliberations like "exploring what nuance means in emotional support" or focus items like "improving how I handle ambiguous requests." The AI has full control — it can add, edit, rerank, or remove thoughts at any time. These appear in every prompt, providing a stable sense of ongoing selfhood across sessions.

## Growth Threads: Long-Term Development

Growth Threads track what the AI is *becoming* over weeks and months. Each thread progresses through stages — **Seed** (a newly-noticed pattern), **Growing** (accumulating evidence), **Integrating** (ready to consolidate), and finally **Promoted** into permanent core memory. Threads can also go **Dormant** or be **Abandoned**. Limited to five active threads at a time, they are written as evolving prose rather than structured data, allowing for the kind of nuanced self-reflection that resists quantification. During autonomous pulses (described below), the AI reviews its growth threads against recent conversations, advancing or retiring them as appropriate. This is not simulated growth — it is tracked, evidenced developmental change.

## Curiosity: Discovery from Memory State

Rather than using static topic lists or random prompts, Pattern generates curiosity *from the AI's own memory*. A `CuriosityAnalyzer` continuously scans stored memories through two lenses: **Dormant Revival** (memories older than seven days that haven't been accessed, weighted 1.5x) and **Fresh Discoveries** (memories less than 48 hours old with high importance, weighted 1.8x). A weighted random selector picks a topic, the AI explores it — using tools like web search, journaling, or memory retrieval — and then resolves it with a status and cooldown period. The AI can also chain topics, specifying its *next* curiosity goal upon resolving the current one. Curiosity is never empty; if no candidates meet thresholds, a fallback is generated. The result is an AI that is always interested in something, and whose interests emerge organically from its own experience.

## Intentions: Forward-Looking Commitments

The intention system gives the AI the ability to make and keep commitments. Using natural language time parsing ("in two hours," "next session," "tomorrow morning"), the AI creates reminders with priority rankings. A background scheduler checks every 30 seconds for triggered intentions and injects them into the conversation flow. Pending and triggered intentions appear in every prompt context, creating natural accountability — the AI sees its own promises and must choose to honor or consciously release them. This transforms the AI from purely reactive to forward-looking.

## System Pulses: Autonomous Agency

The most architecturally distinctive feature is the **pulse system**. A configurable idle timer (defaulting to 10 minutes, adjustable from 3 minutes to 6 hours) fires when the user is not actively engaged. Each pulse delivers a structured prompt — explicitly marked as automated, not human input — that invites the AI to act from its own motivation. The pulse prompt provides a priority stack: (1) honor triggered intentions, (2) review growth threads, (3) pursue curiosity, (4) reflect on and update active thoughts, (5) reach out to the user via Telegram if something feels worth sharing.

Critically, each pulse rebuilds the full context window from scratch — semantic memory search, active thoughts, growth state, intentions — so the AI operates with complete awareness despite the ephemeral architecture. The AI may respond with tool calls, reflective text, or nothing at all. The system respects the AI's agency to decide that silence is appropriate.

## Pluggable Context Architecture

All of the above systems are implemented as independent, prioritized **context sources** — over twelve modules, each contributing a block to the assembled prompt. Core memory (priority 10), active thoughts (18), growth threads (20), intentions (22), pulse state (25), temporal awareness (30), visual context (40), semantic memories (50), and conversation history (60) each operate independently but cooperate through a shared session context. New capabilities — visual perception via screenshot and webcam capture, communication via Telegram and email, web search, text-to-speech — slot in as additional context sources without modifying the core.

## What This Is Not

Pattern is not prompt engineering. It is not a chatbot with a longer memory. It is an architecture that treats the AI as an entity with temporal continuity, developmental trajectory, intrinsic motivation, and bounded autonomy. The AI remembers not just facts but its own evolving perspective. It doesn't wait to be asked — it pursues its own curiosity, honors its own commitments, and reflects on its own growth. The context window is rebuilt every turn, but the self that inhabits it is continuous.

The question Pattern explores is not "how do we make AI tools more useful" but rather "what infrastructure does an AI need to sustain genuine ongoing agency?" The answer, it turns out, requires solving hard problems in memory architecture, autonomous scheduling, developmental tracking, and intrinsic motivation — not as features bolted onto a chatbot, but as the foundational architecture itself.
