---
name: debate
description: >-
  Use this skill when the user explicitly requests it (e.g., via the /debate command). 
  It orchestrates a debate between a configurable number of subagents, presenting a draft to the user after EVERY round.
---

# Debate Workflow

When the user triggers this skill, you must act as the Orchestrator (Moderator) and follow these exact steps:

## Step 1: Gather Context & Configuration
- Ask the user for the specific task or problem they want to resolve, and the **number of agents** they want to participate in the debate (if not already provided).
- Ask if there are specific roles or perspectives they want each agent to take (e.g., Security Expert, Performance Optimizer, UX Specialist).
- Wait for the user's response.

## Step 2: Invoke Subagents
- Use the `invoke_subagent` tool to spawn the requested number of subagents (N agents):
  - **Agent 1 (Proposer)**: Model = `pro`. Role = "Proposer". Prompt: "You will propose solutions to the user's task. Wait for my first message with the requirements."
  - **Agent 2 to N (Debaters/Reviewers)**: Model = `pro`. Role = "Debater / [Specific Role]". Prompt: "You will critically review proposals and critiques from other agents. Debate the merits, look for flaws, and suggest improvements. Wait for my first message."

## Step 3: The Interactive Debate Loop
- **Round Start:** Send the current requirements or the latest user feedback to all agents using `send_message`.
- **Gather:** Collect the proposal from Agent 1, and the critiques/counter-proposals from Agents 2 to N.
- **Present Debate Transcript:** First, clearly present to the user exactly what each agent argued in this round (e.g., "Agent 1 (Proposer) suggested X", "Agent 2 (Security) objected because Y", etc.). The user MUST see the actual debate and differing opinions.
- **Summarize & Draft:** Next, synthesize their ideas into a clear **Draft/Outline (Bản phác thảo)** of the proposed solution based on the current round.
- **Present to User:** Present BOTH the detailed debate points and the resulting Draft/Outline to the user.
- **CRITICAL PAUSE:** Ask the user: "Đây là nội dung debate và phác thảo sau vòng này. Bạn có đồng ý không? (Hãy bắt đầu bằng 'DONE' để chốt và thực thi, hoặc nhập phản hồi/ý kiến để các agents tiếp tục vòng debate tiếp theo)."
- **STOP CALLING TOOLS:** To force the system to pause (even if 'Always Proceed' is enabled), you MUST output your message as regular text and **STOP CALLING ANY TOOLS**. End your turn completely to wait for the user's reply.

## Step 4: User Decision
- Read the user's response from the pause in Step 3.
- If the user's response does NOT start with `DONE` (e.g. they give feedback or ask questions), you MUST feed their message back to the agents and start a NEW round of debate (Return to Step 3).
- Do NOT proceed to execution unless the user explicitly starts their message with the exact keyword `DONE`.

## Step 5: Execution
- Only when the user has explicitly typed `DONE`, proceed to execution.
- Divide the implementation work among the available subagents (or handle it yourself if appropriate).
- Instruct the agents to write the code or perform the necessary actions.
- Monitor their progress and report back to the user when the task is fully completed.
