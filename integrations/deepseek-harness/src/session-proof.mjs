import { relative, sep } from "node:path";

import { CallId, createAssistantMessage, createToolResultMessage, createUserMessage } from "@deepseek-ai/dsh-llm";
import { SESSION_FORMAT_VERSION, Session, SessionId } from "@deepseek-ai/dsh-session";

const HIDDEN_PAPER_RAG_METADATA = {
  conversation_id: "agent-session-proof",
  actor_id: "system",
  caller: "deepseek_harness",
  request_boundary_id: "boundary-session-proof",
  tool_call_id: "call-session-proof",
};
const TEST_SECRET = "session-proof-secret-token";

function compactJson(value) {
  return JSON.stringify(value);
}

function containsAny(haystack, needles) {
  return needles.some((needle) => haystack.includes(needle));
}

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasRecordedApprovalDecision(event) {
  if (event?.type !== "tool/result" || !isRecord(event.data.meta)) {
    return false;
  }
  const { approval } = event.data.meta;
  return (
    isRecord(approval) &&
    approval.decision === "allowed-once" &&
    approval.scope === "direct-human-request-boundary"
  );
}

function turnNumber(event) {
  return event?.type === "turn/start" || event?.type === "turn/end"
    ? event.data.turn
    : undefined;
}

function isSessionRootVersioned(paths) {
  const relativeSessionRoot = relative(paths.runtimeRoot, paths.sessionRoot);
  return relativeSessionRoot.split(sep).join("/") === `versions/${paths.dshVersion}/sessions`;
}

function eventTypes(events) {
  return events.map((event) => event.type);
}

function appendProofTurn(session) {
  const turn = 0;
  const step = 0;
  const callId = CallId(HIDDEN_PAPER_RAG_METADATA.tool_call_id);
  const modelArguments = { question: "Is the indexed corpus available?" };

  session.append("turn/start", { turn });
  session.append(
    "user/message",
    createUserMessage({
      source: { kind: "user" },
      content: [{ type: "text", text: "Check Paper RAG status." }],
    }),
    { surfaceOp: "append" },
  );
  session.append("step/start", { turn, step });
  const toolCall = session.append("tool/call", {
    turn,
    step,
    callId,
    name: "paper_status",
    arguments: compactJson(modelArguments),
  });
  const toolResult = session.append(
    "tool/result",
    {
      turn,
      step,
      message: createToolResultMessage({
        callId,
        content: [{ type: "text", text: "ok trace_id=trace-session-proof" }],
        isError: false,
      }),
      meta: {
        approval: {
          decision: "allowed-once",
          scope: "direct-human-request-boundary",
        },
      },
    },
    { surfaceOp: "append", sourceEventSeqs: [toolCall.seq] },
  );
  session.append(
    "assistant/message",
    {
      turn,
      step,
      message: createAssistantMessage({
        source: { provider: "session-proof", model: "offline" },
        content: [{ type: "text", text: "Paper RAG status is ok." }],
      }),
    },
    { surfaceOp: "append", sourceEventSeqs: [toolResult.seq] },
  );
  session.append("step/end", { turn, step });
  session.append("turn/end", { turn, reason: { kind: "completed" } });

  return { callId, modelArguments };
}

function appendContinuationTurn(session) {
  const turn = 1;
  session.append("turn/start", { turn });
  session.append("turn/end", { turn, reason: { kind: "completed" } });
}

function toolCallEvents(events) {
  return events.filter((event) => event.type === "tool/call");
}

export function runDshSessionCompatibilityProof(paths) {
  const session = Session.create(SessionId("session-proof"));
  const { callId, modelArguments } = appendProofTurn(session);
  const originalEvents = session.events;
  const originalDerivedMessages = session.deriveMessages();
  const restored = Session.fromRestore(session.id, structuredClone(originalEvents), session.header);
  const restoredBeforeContinuation = restored.events;
  const restoredDerivedMessages = restored.deriveMessages();
  appendContinuationTurn(restored);

  const restoredJson = compactJson(restored.events);
  const restoredDerivedJson = compactJson(restored.deriveMessages());
  const leakedNeedles = [
    "_meta",
    "paper_rag",
    "conversation_id",
    "request_boundary_id",
    HIDDEN_PAPER_RAG_METADATA.conversation_id,
    HIDDEN_PAPER_RAG_METADATA.request_boundary_id,
  ];
  const secretNeedles = [TEST_SECRET];
  const restoredToolCalls = toolCallEvents(restored.events);
  const proofToolCall = restoredToolCalls.find((event) => event.data.callId === callId);
  const parsedArguments =
    proofToolCall === undefined ? undefined : JSON.parse(proofToolCall.data.arguments);
  const toolResult = restored.events.find((event) => event.type === "tool/result");

  return {
    session_format_version: SESSION_FORMAT_VERSION,
    session_root_versioned: isSessionRootVersioned(paths),
    event_types: eventTypes(restoredBeforeContinuation),
    restored_history_order_matches:
      compactJson(restoredBeforeContinuation.slice(0, originalEvents.length)) ===
      compactJson(originalEvents),
    restored_derived_messages_match:
      compactJson(restoredDerivedMessages) === compactJson(originalDerivedMessages),
    tool_call_arguments_are_model_only:
      compactJson(parsedArguments) === compactJson(modelArguments) &&
      !containsAny(proofToolCall?.data.arguments ?? "", leakedNeedles),
    hidden_metadata_not_in_session:
      !containsAny(restoredJson, leakedNeedles) && !containsAny(restoredDerivedJson, leakedNeedles),
    secret_not_in_session:
      !containsAny(restoredJson, secretNeedles) &&
      !containsAny(restoredDerivedJson, secretNeedles),
    approval_decision_recorded: hasRecordedApprovalDecision(toolResult),
    can_continue_new_turn: turnNumber(restored.events.at(-2)) === 1,
    no_duplicate_historical_tool_calls:
      restoredToolCalls.filter((event) => event.data.callId === callId).length === 1,
  };
}
