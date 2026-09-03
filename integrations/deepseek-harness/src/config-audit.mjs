function rowBlock(text, id) {
  const pattern = new RegExp(`(^|\\n)- id: ${escapeRegex(id)}\\n[\\s\\S]*?(?=\\n- id: |$)`);
  return text.match(pattern)?.[0] ?? "";
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function check(id, passed, detail) {
  return {
    id,
    status: passed ? "PASS" : "FAIL",
    detail,
  };
}

export function auditDshConfigDump(text) {
  const webserver = rowBlock(text, "webserver");
  const telemetry = rowBlock(text, "session-telemetry-otel");
  const credentials = rowBlock(text, "credentials");
  const timeout = rowBlock(text, "timeout-policy");
  const presets = rowBlock(text, "agent-presets");

  const checks = [
    check(
      "web-loopback",
      /host:\s*['"]?127\.0\.0\.1['"]?/.test(webserver),
      "webserver host must resolve to 127.0.0.1",
    ),
    check(
      "telemetry-disabled",
      /disabled:\s*true/.test(telemetry) || /mode:\s*['"]?DISABLED['"]?/.test(telemetry),
      "session telemetry must be disabled by profile or env patch",
    ),
    check(
      "credential-path",
      /PAPER_RAG_DSH_CREDENTIALS_PATH/.test(credentials),
      "credentials provider must use the repo-managed credential path env",
    ),
    check(
      "timeout-policy",
      /@deepseek-ai\/dsh-tool-call-timeout-policy/.test(timeout) &&
        !/disabled:\s*true/.test(timeout),
      "Host timeout policy must be present and enabled",
    ),
    check(
      "paper-preset-default",
      /default:\s*paper-research/.test(presets),
      "paper-research must be the default Agent preset",
    ),
  ];

  return {
    schema_version: 1,
    passed: checks.every((item) => item.status === "PASS"),
    checks,
  };
}
