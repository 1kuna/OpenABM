import type { Project, TraceDetail, TraceEnvelope } from "./types";

export const fixtureProjects: Project[] = [
  { project_id: "proj_demo", name: "Demo Project", created_at: "2026-05-12T10:00:00Z" }
];

export const fixtureDetails: TraceDetail[] = [
  {
    trace: {
      trace_id: "trace_wrong_tool",
      project_id: "proj_demo",
      session_id: "session_002",
      user_external_id: "user_synthetic_002",
      root_span_id: "span_wrong_tool_root",
      environment: "fixture",
      status: "error",
      started_at: "2026-05-12T10:05:00Z",
      ended_at: "2026-05-12T10:05:10Z",
      tags: ["support", "fixture", "failure"],
      attributes: { channel: "chat" },
      prompt_version_id: null,
      agent_config_version_id: null,
      deployment_context_id: null,
      tool_version_ids: [],
      summary: "Agent used an order lookup tool for a refund decision that required policy lookup."
    },
    spans: [
      {
        trace_id: "trace_wrong_tool",
        span_id: "span_wrong_tool_root",
        parent_span_id: null,
        project_id: "proj_demo",
        name: "refund_agent",
        span_type: "agent",
        status: "error",
        started_at: "2026-05-12T10:05:00Z",
        ended_at: "2026-05-12T10:05:10Z",
        input: { mode: "inline", value: "Refund my damaged order.", redaction_state: "raw" },
        output: { mode: "inline", value: "I cannot find your order status.", redaction_state: "raw" },
        attributes: { "error.type": "wrong_tool" },
        events: [
          {
            name: "feedback.user_correction",
            time: "2026-05-12T10:05:11Z",
            attributes: { message: "You should have checked the refund policy." }
          }
        ],
        links: []
      },
      {
        trace_id: "trace_wrong_tool",
        span_id: "span_wrong_tool_order_lookup",
        parent_span_id: "span_wrong_tool_root",
        project_id: "proj_demo",
        name: "lookup_order",
        span_type: "tool",
        status: "ok",
        started_at: "2026-05-12T10:05:02Z",
        ended_at: "2026-05-12T10:05:03Z",
        input: { mode: "inline", value: { order_id: "synthetic" }, redaction_state: "masked" },
        output: { mode: "inline", value: { status: "delivered" }, redaction_state: "raw" },
        attributes: { "tool.name": "order_lookup", "tool.success": true },
        events: [],
        links: []
      }
    ],
    reconstruction: {
      span_tree: [],
      timeline_rows: [
        {
          span_id: "span_wrong_tool_root",
          parent_span_id: null,
          name: "refund_agent",
          span_type: "agent",
          status: "error",
          started_at: "2026-05-12T10:05:00Z",
          ended_at: "2026-05-12T10:05:10Z"
        },
        {
          span_id: "span_wrong_tool_order_lookup",
          parent_span_id: "span_wrong_tool_root",
          name: "lookup_order",
          span_type: "tool",
          status: "ok",
          started_at: "2026-05-12T10:05:02Z",
          ended_at: "2026-05-12T10:05:03Z"
        }
      ],
      missing_parent_group: [],
      incomplete_span_ids: [],
      warnings: [],
      payload_availability: {
        span_wrong_tool_root: { input: "raw", output: "raw" },
        span_wrong_tool_order_lookup: { input: "masked", output: "raw" }
      }
    }
  }
];

export const fixtureTraces: TraceEnvelope[] = fixtureDetails.map((detail) => detail.trace);
