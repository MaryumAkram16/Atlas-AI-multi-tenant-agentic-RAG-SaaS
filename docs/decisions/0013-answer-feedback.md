# 0013. Answer feedback

- Status: Accepted
- Date: 2026-11-26

## Context
Owners need to know which answers fail, and the evaluation datasets (ADR 0012)
need realistic questions. Conversations are private to their author.

## Decision
- `message_feedback` (migration 0008): one row per user and assistant message,
  rating `up`/`down`, an optional reason for `down` (incorrect, missing
  information, wrong citation, outdated, other) and an optional comment.
- Only the conversation's author can rate, change or remove feedback (RLS
  helper `owns_assistant_message`). Owners/admins can read all feedback.
- The **question** is copied onto the row so admins can review it without
  reading the conversation; the **answer is not**, because it derives from
  documents the reviewer may not be able to read. The feedback form says who
  will see what.
- Admins turn a thumbs down into an evaluation case from the Evaluations page,
  adding the facts a correct answer must contain (existing cases endpoint).

## Consequences
- Giving feedback shares the question with admins; users who do not want that
  can simply not rate.
- Feedback outlives document revocation (it holds no document content) and is
  deleted with the message.
