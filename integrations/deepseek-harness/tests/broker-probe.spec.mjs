import { describe, expect, test } from "vitest";

import { runBrokerCompatibilityProbe } from "../src/broker-probe.mjs";
import { pathsFor } from "../src/paths.mjs";

const paths = pathsFor();

describe("DeepSeek Harness G0 compatibility probe", () => {
  test("proves same-version Session resume without persisting hidden Paper RAG metadata", async () => {
    const probe = await runBrokerCompatibilityProbe(paths);

    expect(probe.dsh_session).toMatchObject({
      session_format_version: 0,
      session_root_versioned: true,
      restored_history_order_matches: true,
      restored_derived_messages_match: true,
      tool_call_arguments_are_model_only: true,
      hidden_metadata_not_in_session: true,
      secret_not_in_session: true,
      approval_decision_recorded: true,
      can_continue_new_turn: true,
      no_duplicate_historical_tool_calls: true,
    });
    expect(probe.dsh_session.event_types).toEqual([
      "turn/start",
      "user/message",
      "step/start",
      "tool/call",
      "tool/result",
      "assistant/message",
      "step/end",
      "turn/end",
      "session/end-seed",
    ]);
    expect(probe.lifecycle).toMatchObject({
      dispose_agent_keeps_shared_child_alive: true,
      preset_edit_creates_new_generation: true,
      generation_count_is_diagnostic: true,
      host_shutdown_closes_all_generations: true,
    });
  });
});
