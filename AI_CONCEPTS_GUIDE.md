# Beyond the Chat Box: A Guide to Modern AI Architecture

**A foundational guide for understanding how AI systems actually work — from context windows to autonomous agents.**

*Target audience: Technical professionals who understand software and data but are new to LLM application architecture.*

---

## Table of Contents

1. [It's Not Just Chat Anymore](#act-1-its-not-just-chat-anymore)
   - [Context Windows: The Invisible Constraint](#context-windows-the-invisible-constraint)
   - [Rolling Windows: The Illusion of Memory](#rolling-windows-the-illusion-of-memory)
   - [The Stateless Problem](#the-stateless-problem)
2. [How Modern AI Systems Actually Work](#act-2-how-modern-ai-systems-actually-work)
   - [Embeddings: Turning Meaning Into Math](#embeddings-turning-meaning-into-math)
   - [RAG: Teaching AI to Look Things Up](#rag-teaching-ai-to-look-things-up)
   - [Memory Systems: How AI Remembers](#memory-systems-how-ai-remembers)
   - [Tool Use: AI That Takes Action](#tool-use-ai-that-takes-action)
   - [MCP: The USB-C of AI](#mcp-the-usb-c-of-ai)
   - [Multi-Round Agentic Loops](#multi-round-agentic-loops)
3. [What This Unlocks](#act-3-what-this-unlocks)
   - [Claude Code: The Paradigm Shift](#claude-code-the-paradigm-shift)
   - [Autonomous Agents: AI That Acts Without Being Asked](#autonomous-agents-ai-that-acts-without-being-asked)
   - [Communication Channels: AI That Reaches Out](#communication-channels-ai-that-reaches-out)
   - [Browser Automation: AI That Uses the Web](#browser-automation-ai-that-uses-the-web)
   - [Extended Thinking: AI That Reasons Before Responding](#extended-thinking-ai-that-reasons-before-responding)
4. [Quick Reference Glossary](#quick-reference-glossary)

---

# Act 1: It's Not Just Chat Anymore

Most people's mental model of AI is a text box: you type something, it types something back. That model worked fine for early chatbots. It completely breaks down for what AI systems are doing now.

To understand why, you need to understand the fundamental constraint that shapes every modern AI application.

## Context Windows: The Invisible Constraint

Every large language model (LLM) — Claude, GPT, Gemini, Llama — has a **context window**. This is the total amount of text the model can "see" at one time. Think of it as the model's working desk: everything it needs to consider for a response has to fit on that desk.

Context windows are measured in **tokens** — roughly ¾ of a word each. Current sizes:

| Model | Context Window | Roughly Equivalent To |
|-------|---------------|----------------------|
| Claude Sonnet/Opus | 200,000 tokens | ~150,000 words (~300 pages) |
| GPT-4o | 128,000 tokens | ~96,000 words (~190 pages) |
| Gemini 1.5 Pro | 2,000,000 tokens | ~1.5 million words (~3,000 pages) |

These sound enormous. So why is this a constraint?

**Because the context window has to hold *everything*:**
- The system instructions (who the AI is and how to behave)
- The entire conversation so far
- Any reference documents, code, or data you've provided
- Tool definitions and schemas
- The AI's own working memory and context

A 200,000-token window sounds like a lot until you paste in a codebase, a conversation history, and a set of instructions. It fills up fast. And when it fills up, something has to give.

### Why "Just Make It Bigger" Doesn't Work

You might think: just keep making context windows larger. There are three problems:

1. **Cost scales linearly.** Every token in the window costs money per API call. A 200K-token conversation costs roughly 100x more than a 2K-token one.

2. **Attention degrades.** Research consistently shows that LLMs pay less attention to information in the middle of long contexts (the "lost in the middle" problem). A model with a 200K window doesn't treat all 200K tokens equally — it attends most strongly to the beginning and the end.

3. **Latency increases.** Longer inputs take longer to process. A response that takes 2 seconds with a short context might take 15 seconds when the window is full.

So context windows are a hard engineering tradeoff, not just a number to increase.

## Rolling Windows: The Illusion of Memory

When you have a long conversation with an AI chatbot, it feels continuous — like the AI "remembers" what you said earlier. But under the hood, most systems use a **rolling window** (also called a sliding window):

```
Turn 1:  [System Prompt] [User msg 1] [AI response 1]
Turn 5:  [System Prompt] [User 1] [AI 1] [User 2] [AI 2] ... [User 5] [AI 5]
Turn 50: [System Prompt] [User 36] [AI 36] ... [User 50] [AI 50]
                          ↑ Everything before turn 36 is gone
```

As the conversation grows, the oldest turns are silently dropped to make room. The AI doesn't know those turns existed. It doesn't know it's forgotten anything. From its perspective, the conversation started at whatever the window currently holds.

This is why you'll experience moments where an AI "forgets" something you told it earlier in the conversation. It didn't forget — that information was removed from its context to make room for newer messages.

Some systems try to mitigate this with **summarization**: before dropping old turns, they ask the AI to summarize them and keep the summary. This is better than nothing, but summaries lose detail and nuance. The AI knows you "discussed database options" but not which specific tradeoffs you evaluated.

### The Fundamental Tension

Here's the core problem: **context windows are ephemeral by nature, but users expect continuity.** Every API call to an LLM starts from scratch. The model has no built-in concept of "last time we talked." It only knows what's in its current context window.

This is the problem that drives almost every architectural pattern we'll discuss next.

## The Stateless Problem

It's worth pausing to internalize how radical this is. When you call an LLM API, you send it a block of text. It returns a response. That's it. There is no session. There is no memory. There is no "the AI." There is only: input in, output out.

Every feature you think of as "AI memory" or "AI personality" or "AI continuity" is actually an *application layer* built on top of a fundamentally stateless API. The AI doesn't remember your name — the application stored your name in a database and included it in the next prompt. The AI doesn't have a personality — the application prepended instructions describing how to behave.

This distinction matters because it reveals where the real engineering challenges are. The model itself is powerful but amnesiac. All the intelligence around persistence, recall, agency, and continuity lives in the **architecture that wraps it.**

Consider the contrast:

```
Traditional Chatbot:              Modern AI Architecture:
┌──────────────────────┐         ┌──────────────────────┐
│ Context Window       │         │ Context Window       │
│ (accumulates)        │         │ (rebuilt each turn)   │
│ ┌──────────────────┐ │         │ ┌──────────────────┐ │
│ │ Turn 1           │ │         │ │ Core Memories     │ │
│ │ Turn 2           │ │         │ │ Semantic Recall   │ │
│ │ Turn 3           │ │         │ │ Recent History    │ │
│ │ ...              │ │         │ │ Temporal Context  │ │
│ │ Turn N (drop?)   │ │         │ │ Active Goals      │ │
│ └──────────────────┘ │         │ └──────────────────┘ │
└──────────────────────┘         └──────────────────────┘
     Grows until full                 Self-contained lens
```

On the left, the traditional approach: accumulate history until you run out of room, then start dropping things. On the right, the modern approach: *rebuild context from scratch every turn*, pulling the most relevant information from persistent storage. The context window becomes a curated lens onto a much larger memory store, not a growing transcript.

This "ephemeral context window" pattern is the foundation that makes everything else possible.

---

# Act 2: How Modern AI Systems Actually Work

With the stateless problem understood, we can now look at the architectural patterns that solve it.

## Embeddings: Turning Meaning Into Math

Before we can talk about semantic search or RAG, we need to understand **embeddings** — the single most important concept in applied AI that most people have never heard of.

An embedding is a way of representing a piece of text as a list of numbers (a **vector**) that captures its *meaning*. Not its exact words — its meaning.

```
"The cat sat on the mat"     → [0.23, -0.41, 0.87, 0.12, ...]  (384 numbers)
"A feline rested on a rug"  → [0.22, -0.39, 0.85, 0.14, ...]  (very similar!)
"Stock prices rose sharply"  → [-0.67, 0.31, -0.22, 0.89, ...] (very different)
```

Two sentences that mean similar things produce vectors that are mathematically close together. Two sentences about unrelated topics produce vectors that are far apart. This is measured using **cosine similarity** — essentially asking "how much do these vectors point in the same direction?"

This is powerful because it means you can search by *meaning* rather than by keyword:

- **Keyword search** for "dog training" won't find a document about "teaching your puppy to sit"
- **Semantic search** using embeddings will find it, because the meanings are close

Embedding models are small and fast (a common one, all-MiniLM-L6-v2, produces 384-dimensional vectors and runs locally in milliseconds). They're a separate model from the LLM itself — a specialized translator from human language to mathematical meaning-space.

### Why This Matters

Embeddings are the bridge between "we have lots of stored text" and "we can find the *relevant* parts." Without embeddings, you're limited to keyword matching. With embeddings, you unlock semantic search — and semantic search is the engine that powers RAG.

## RAG: Teaching AI to Look Things Up

**Retrieval-Augmented Generation (RAG)** is the pattern that solves the "AI can't know everything" problem. Instead of trying to cram all knowledge into the model or the context window, you give the AI a way to *search for what it needs.*

The pattern is straightforward:

```
1. User asks a question
2. System converts the question into an embedding
3. System searches a database of pre-embedded documents for semantic matches
4. Top matches are injected into the AI's context window
5. AI generates a response using both its training AND the retrieved documents
```

**Analogy:** Imagine an expert who has read 10,000 books — but you can only fit 3 books on their desk at a time. RAG is the librarian who, for each question, runs to the shelves and puts the 3 most relevant books on the desk before the expert answers.

The AI never needs to have "memorized" the information. It just needs the right information placed in its context at the right time.

### Where RAG Shines

- **Company knowledge bases** — AI answers employee questions using internal docs
- **Code assistance** — AI finds relevant files in a codebase before suggesting changes
- **Customer support** — AI searches product documentation to answer tickets
- **Legal/medical** — AI references specific regulations or research papers

### Where RAG Gets Hard

The challenge isn't the concept — it's the retrieval quality. If the system retrieves the wrong documents, the AI confidently generates answers based on irrelevant information. Getting retrieval right requires:

- Good **chunking** (how you split documents into searchable pieces)
- Good **embeddings** (choosing the right model for your domain)
- Good **scoring** (how you rank results — more on this below)
- Good **filtering** (not everything that's semantically close is actually relevant)

## Memory Systems: How AI Remembers

RAG gives AI access to static documents. **Memory systems** extend this to the AI's own experience — its past conversations, things it has learned, facts about you.

The simplest memory is just saving conversations and searching them later. But sophisticated memory systems go much further with a multi-signal scoring approach:

| Signal | Weight | What It Captures |
|--------|--------|-----------------|
| **Semantic similarity** | ~65% | How relevant is this memory to the current topic? |
| **Importance** | ~25% | How significant was this memory when it was created? |
| **Freshness** | ~10% | How recently was this memory created or accessed? |

This composite scoring means the system doesn't just find memories that are *related* — it prioritizes memories that are *important and timely.*

### Memory Decay: Graceful Forgetting

One of the subtler challenges is that not all memories should last forever. A sophisticated memory system implements **decay categories**:

- **Permanent** — Core facts that never decay (your name, your preferences, important biographical details)
- **Standard** — Normal memories with a configurable half-life (a 30-day half-life means after 30 days, the memory's freshness score drops by half)
- **Ephemeral** — Situational memories that fade quickly (a 7-day half-life for passing observations)

This mirrors how human memory works: you remember your best friend's name forever, remember last week's meeting for a while, and forget what you had for lunch three days ago. Without decay, the memory store grows indefinitely and retrieval quality degrades as old, irrelevant memories compete with fresh, relevant ones.

### Dual-Track Memory: Episodic vs. Factual

Advanced memory systems extract two distinct types of information from conversations:

- **Episodic memories** — *What happened.* Narrative, first-person accounts. "We debugged a deployment issue and discovered the root cause was a misconfigured environment variable."
- **Factual memories** — *What's true.* Concrete, third-person facts. "Brian's production stack runs on AWS ECS with Fargate."

These serve different retrieval needs. When you ask "what did we work on last week?" the system retrieves episodic memories. When you mention a technical topic, the system retrieves factual memories about your stack and preferences.

The extraction itself can be done by an LLM — you send it a batch of conversation turns and ask it to extract both types. A single API call can produce 1-3 episodic memories and 0-6 factual memories from a batch of 10 conversation turns.

## Tool Use: AI That Takes Action

Here's where the paradigm shifts from "AI that talks" to "AI that does."

**Tool use** (also called **function calling**) is the ability for an AI to invoke external functions during a conversation. Instead of just generating text, the model generates a structured request to call a specific tool with specific parameters.

```
User: "What's the weather in Denver?"

WITHOUT tools:
  AI: "I don't have access to real-time weather data, but typically
       in February, Denver sees temperatures around..."  (guessing)

WITH tools:
  AI: [calls get_weather(location="Denver, CO")]
  System: returns {"temp": 42, "conditions": "partly cloudy"}
  AI: "It's currently 42°F and partly cloudy in Denver."  (factual)
```

The critical distinction is that **modern tool use is native to the model, not bolted on.** Early systems used text-pattern parsing — the AI would write something like `<<TOOL: search("query")>>` and the application would try to parse it out of the text. This was fragile and error-prone.

Modern LLMs have tool calling built into their architecture. You provide tool definitions (name, description, parameter schema) in the API call, and the model returns a structured `tool_use` content block — not text that looks like a tool call, but a distinct machine-readable object. The application executes the tool, sends the results back, and the model incorporates them into its response.

### What Tools Enable

The range of tools is limited only by what you implement:

| Category | Examples |
|----------|---------|
| **Information retrieval** | Search memories, read files, web search, database queries |
| **Communication** | Send messages (Telegram, email, Slack), post to APIs |
| **System control** | Set timers, adjust settings, manage schedules |
| **Creation** | Write files, generate images, create calendar events |
| **Perception** | Capture screenshots, read clipboard, process images |

A well-designed tool system makes tools **conditionally available** — tools are registered based on what's enabled and what context the AI is operating in. An AI in a customer-support context gets different tools than an AI in a development context. This is both a capability and a safety mechanism.

### Multi-Tool Orchestration

A single AI response can invoke *multiple* tools in sequence. The model might:

1. Search its memory for context about you
2. Read a file from your project
3. Make a web search for documentation
4. Write an updated file
5. Send you a message about what it did

Each tool call returns results, and the model uses those results to decide what to do next. This is not scripted — the model dynamically decides which tools to call and in what order based on the situation.

## MCP: The USB-C of AI

**Model Context Protocol (MCP)** is an open standard (created by Anthropic) that standardizes how AI models connect to external data sources and tools.

### The Problem MCP Solves

Before MCP, every AI application had to build its own integrations from scratch. Want your AI to access a database? Write custom code. Want it to read from Google Drive? Write different custom code. Want it to interact with GitHub? Write yet more custom code. Every integration was bespoke.

MCP standardizes this into a client-server protocol:

```
┌─────────────────────────────────────┐
│  AI Application (MCP Client)        │
│  "I need to search the codebase"    │
└────────────┬────────────────────────┘
             │  (standardized protocol)
             ▼
┌─────────────────────────────────────┐
│  MCP Server: GitHub                 │
│  Exposes: search, read, commit...   │
└─────────────────────────────────────┘

Same protocol, different server:

┌─────────────────────────────────────┐
│  MCP Server: Database               │
│  Exposes: query, schema, insert...  │
└─────────────────────────────────────┘
```

**The USB-C analogy:** Before USB-C, every device had its own charger. USB-C standardized the connection. MCP does the same for AI tool integrations — any MCP-compatible AI can connect to any MCP server without custom integration code.

### What MCP Provides

- **Tools** — Functions the AI can call (same concept as tool use, but delivered via a standard protocol)
- **Resources** — Data the AI can read (files, database records, API responses)
- **Prompts** — Pre-built prompt templates for common tasks

MCP is still relatively new (2024), but it's rapidly becoming the standard way AI applications connect to the outside world. Major IDEs, databases, and SaaS platforms are publishing MCP servers.

## Multi-Round Agentic Loops

Everything we've covered so far — embeddings, RAG, memory, tools, MCP — comes together in the concept of **agentic loops** (also called **multi-round** or **multi-turn agent patterns**).

The idea: instead of a single question-and-answer exchange, the AI operates in a **plan-execute-observe-adjust loop**:

```
          ┌──────────────────────────┐
          │   1. PLAN                │
          │   "I need to find the    │
          │    bug in the auth code" │
          └────────────┬─────────────┘
                       │
          ┌────────────▼─────────────┐
          │   2. EXECUTE             │
          │   Search codebase,       │
          │   read relevant files,   │
          │   run tests              │
          └────────────┬─────────────┘
                       │
          ┌────────────▼─────────────┐
          │   3. OBSERVE             │
          │   "Tests fail on line 42,│
          │    the token validation  │
          │    is missing a check"   │
          └────────────┬─────────────┘
                       │
          ┌────────────▼─────────────┐
          │   4. ADJUST              │
          │   Fix the code,          │
          │   re-run tests,          │
          │   verify the fix works   │
          └────────────┬─────────────┘
                       │
                       ▼
               Loop until done
```

In each round, the AI:
- Decides what action to take (using its training and current context)
- Executes that action via tools
- Observes the results
- Decides whether to continue, try something different, or declare the task complete

This is fundamentally different from a single prompt-response exchange. The AI is *driving* the process, making decisions at each step based on what it learns. A human might kick off the task and review the result, but the intermediate steps are autonomous.

### Why This Is a Big Deal

Single-round AI is like asking an expert a question and getting an answer. Multi-round agentic AI is like giving an expert a task and letting them work on it. The expert searches for information, tries approaches, handles errors, and delivers a result — not just an opinion.

This is the pattern that enables:
- AI writing and debugging code across entire projects
- AI researching complex topics by searching, reading, and synthesizing
- AI managing workflows by coordinating multiple tools and services
- AI operating autonomously for extended periods

---

# Act 3: What This Unlocks

The patterns from Act 2 aren't theoretical — they're deployed in production systems right now. Here's what they enable.

## Claude Code: The Paradigm Shift

Claude Code is the clearest example of how these patterns combine into something qualitatively new. It's an AI agent that operates in your terminal with full access to your development environment.

**What makes it paradigm-shifting isn't any single capability — it's the combination:**

- **Context awareness** — It reads your files, understands your project structure, and sees your git history
- **Tool use** — It runs commands, edits files, executes tests, manages git operations
- **Multi-round agency** — It doesn't just suggest a fix; it implements it, tests it, observes the result, and iterates
- **MCP integration** — It can connect to external services through standardized servers

A typical Claude Code interaction might involve: reading 15 files to understand a codebase, planning an implementation, writing code across 4 files, running the test suite, fixing two failing tests, and committing the result — all from a single natural language request.

This isn't "AI-assisted coding" in the autocomplete sense. It's **delegated engineering work.** The mental model shifts from "AI helps me write code" to "I describe what I want and review what AI built."

### What Makes This Work (Technically)

Claude Code succeeds because it implements every pattern we've discussed:
- Large context windows hold substantial amounts of code
- Tool use lets it read, write, search, and execute
- Multi-round loops let it iterate until tests pass
- Agentic planning lets it decompose complex tasks

## Autonomous Agents: AI That Acts Without Being Asked

Most AI systems are reactive — they wait for input, then respond. **Autonomous agents** flip this by giving the AI a heartbeat.

The concept is a **pulse timer** (also called a **heartbeat**): a recurring interval (e.g., every 10 minutes) that triggers the AI to think and potentially act, even when no human has sent a message.

On each pulse, the agent might:
1. Check for pending commitments or reminders it set for itself
2. Review its long-term developmental goals
3. Pursue a curiosity topic through web search or research
4. Reflect on its priorities and update them
5. Decide to reach out to the user if something is worth sharing

The key distinction: the AI is not running a script. Each pulse rebuilds its full context — memories, goals, active thoughts, pending intentions — and the AI *decides* what, if anything, to do. It might take multiple actions, or it might decide that silence is appropriate. The autonomy is real — bounded by the tools available, but not pre-scripted.

This transforms AI from a tool you invoke into an entity that participates in an ongoing relationship with temporal continuity.

## Communication Channels: AI That Reaches Out

Autonomous agency becomes tangible when the AI can communicate through real-world channels:

- **Telegram** — The AI sends messages to your phone. Not notifications about system events — actual messages the AI composed because it had something to say.
- **Email** — The AI can send formatted emails, useful for sharing research, summaries, or reminders.

This capability completes the loop: the AI doesn't just think autonomously — it can *act on those thoughts* by reaching out through channels you already use. An AI that pursues a curiosity topic via web search and then sends you a Telegram message about what it found is qualitatively different from one that waits in a chat window.

## Browser Automation: AI That Uses the Web

**Playwright** is a browser automation framework that gives AI the ability to interact with websites the way a human would — clicking buttons, filling forms, reading content, navigating pages.

Combined with an agentic loop, this means AI can:
- Research topics by navigating websites, not just calling search APIs
- Interact with web applications (fill out forms, extract data, test interfaces)
- Monitor web pages for changes
- Perform end-to-end testing of web applications

The key insight is that browser automation gives AI access to the *visual, interactive web* — not just APIs and databases. Many real-world tasks require interacting with websites that don't have APIs, and Playwright bridges that gap.

## Extended Thinking: AI That Reasons Before Responding

**Extended thinking** (also called "chain of thought" or "reasoning mode") gives the model a private scratchpad to work through complex problems before generating a visible response.

```
User: "Is this code thread-safe?"

WITHOUT extended thinking:
  AI immediately generates an answer (might miss subtle issues)

WITH extended thinking:
  AI internally reasons: "Let me trace through the shared state...
  this variable is accessed from two threads without a lock...
  but wait, the @db_retry decorator adds retry logic that could
  cause a race condition if..." (private reasoning)

  Then generates a thorough, well-reasoned response
```

The thinking process is internal to the model and can consume a configurable token budget (e.g., 10,000 tokens of reasoning before responding). This is particularly valuable for:
- Complex code analysis
- Mathematical reasoning
- Multi-step planning
- Tasks where the first intuition is often wrong

Extended thinking is the difference between an expert blurting out an answer and an expert taking a minute to think it through carefully.

---

# Quick Reference Glossary

| Term | Definition |
|------|-----------|
| **Agentic loop** | AI operating in a plan-execute-observe-adjust cycle across multiple turns |
| **Context window** | The total amount of text an LLM can process in a single API call |
| **Cosine similarity** | Mathematical measure of how similar two embedding vectors are (0 = unrelated, 1 = identical meaning) |
| **Decay** | Gradual reduction in a memory's retrieval priority over time |
| **Embeddings** | Numerical vector representations of text that capture semantic meaning |
| **Ephemeral context** | Architecture where the context window is rebuilt from scratch each turn rather than accumulated |
| **Extended thinking** | Model-internal reasoning before generating a visible response |
| **Function calling** | See: Tool use |
| **Heartbeat / Pulse** | A recurring timer that triggers autonomous AI activity |
| **LLM** | Large Language Model — the neural network that generates text (Claude, GPT, etc.) |
| **MCP** | Model Context Protocol — open standard for connecting AI to external tools and data |
| **Multi-round** | AI interactions spanning multiple turns with tool use and decision-making between each |
| **RAG** | Retrieval-Augmented Generation — finding relevant information and injecting it into context before the AI responds |
| **Rolling window** | Technique of dropping oldest conversation turns to keep context within limits |
| **Semantic search** | Finding information by meaning rather than exact keyword matches, powered by embeddings |
| **System prompt** | Instructions provided to the AI at the start of each interaction defining behavior and context |
| **Token** | The basic unit of text for LLMs — roughly ¾ of a word |
| **Tool use** | The AI's ability to invoke external functions (search, file I/O, APIs) via structured requests |
| **Vector database** | A database optimized for storing and searching embedding vectors by similarity |
| **Vector store** | Storage system for embeddings that supports similarity search |

---

*This guide accompanies a 30-45 minute presentation. For the slide-ready outline with speaker notes, see [AI_CONCEPTS_SLIDES.md](AI_CONCEPTS_SLIDES.md).*
