import assert from "node:assert/strict";
import test from "node:test";

import type {
  PlanResult,
  ScenarioBootstrapResponse,
  WorldStateSnapshot,
} from "@the-ark/shared-types";

import { responseDestinations } from "../src/derive.ts";

const bootstrap = {
  assets: {
    features: [
      { id: "community-1", properties: { name: "Riverbend" } },
      { id: "shelter-1", properties: { name: "Ridge Shelter" } },
    ],
  },
  plans: [{ plan_id: "plan-a", evaluation_deadline_minutes: 60 }],
  road_network: { features: [] },
} as unknown as ScenarioBootstrapResponse;

const baseWorld = {
  simulation_time_hours: 12,
  prediction_signals: [
    {
      ping_id: "signal-1",
      exposure_asset_id: "community-1",
      priority_score: 82,
      priority_rank: 1,
      priority_level: "high",
      state: "active",
    },
  ],
  community_access: [
    {
      community_id: "community-1",
      isolated: false,
      time_to_isolation_hours: 18,
    },
  ],
  edge_states: [{ edge_id: "edge-1", status: "restricted" }],
} as unknown as WorldStateSnapshot;

const plan = {
  plan_id: "plan-a",
  assignment_results: [
    {
      community_id: "community-1",
      shelter_id: "shelter-1",
      people: 120,
      departure_offset_minutes: 0,
      route_preference: "shortest_safe",
      route: {
        source_node_id: "node-community",
        destination_node_id: "node-shelter",
        node_ids: ["node-community", "node-shelter"],
        edge_ids: ["edge-1"],
        travel_minutes: 14,
      },
      arrival_minutes: 14,
      meets_deadline: true,
      people_evacuated: 120,
    },
  ],
} as unknown as PlanResult;

test("joins an evaluated assignment into an explainable responder destination", () => {
  const [destination] = responseDestinations(bootstrap, baseWorld, plan);

  assert.equal(destination.communityName, "Riverbend");
  assert.equal(destination.shelterName, "Ridge Shelter");
  assert.equal(destination.status, "priority");
  assert.equal(destination.arrivalMinutes, 14);
  assert.equal(destination.deadlineMinutes, 60);
  assert.equal(destination.remainingAccessHours, 6);
  assert.deepEqual(destination.routeEdgeIds, ["edge-1"]);
  assert.equal(destination.restrictedEdgeCount, 1);
  assert.match(destination.instruction, /Proceed to Riverbend/);
  assert.ok(destination.rationale.some((reason) => reason.includes("model signal")));
});

test("marks an infeasible assignment blocked and never exposes a route", () => {
  const blocked = {
    ...plan,
    assignment_results: [
      {
        ...plan.assignment_results[0],
        route: null,
        arrival_minutes: null,
        meets_deadline: false,
        people_evacuated: 0,
      },
    ],
  } as unknown as PlanResult;

  const [destination] = responseDestinations(bootstrap, baseWorld, blocked);

  assert.equal(destination.status, "blocked");
  assert.deepEqual(destination.routeEdgeIds, []);
  assert.match(destination.instruction, /Hold dispatch/);
  assert.ok(destination.rationale[0].includes("No safe route"));
});

test("orders destinations by operational urgency instead of fixture order", () => {
  const expandedBootstrap = {
    ...bootstrap,
    assets: {
      features: [
        ...bootstrap.assets.features,
        { id: "community-2", properties: { name: "Upland" } },
      ],
    },
  } as unknown as ScenarioBootstrapResponse;
  const expandedWorld = {
    ...baseWorld,
    prediction_signals: [
      ...baseWorld.prediction_signals,
      {
        ping_id: "signal-2",
        exposure_asset_id: "community-2",
        priority_score: 20,
        priority_rank: 8,
        priority_level: "low",
        state: "forecast",
      },
    ],
    community_access: [
      ...baseWorld.community_access,
      {
        community_id: "community-2",
        isolated: false,
        time_to_isolation_hours: null,
      },
    ],
  } as unknown as WorldStateSnapshot;
  const lowPriorityAssignment = {
    ...plan.assignment_results[0],
    community_id: "community-2",
  };
  const reversedFixturePlan = {
    ...plan,
    assignment_results: [lowPriorityAssignment, plan.assignment_results[0]],
  } as unknown as PlanResult;

  const destinations = responseDestinations(
    expandedBootstrap,
    expandedWorld,
    reversedFixturePlan,
  );

  assert.deepEqual(
    destinations.map((destination) => destination.communityId),
    ["community-1", "community-2"],
  );
  assert.deepEqual(
    destinations.map((destination) => destination.rank),
    [1, 2],
  );
});

test("places a blocked high-risk destination behind a reachable movement", () => {
  const expandedBootstrap = {
    ...bootstrap,
    assets: {
      features: [
        ...bootstrap.assets.features,
        { id: "community-2", properties: { name: "Upland" } },
      ],
    },
  } as unknown as ScenarioBootstrapResponse;
  const expandedWorld = {
    ...baseWorld,
    prediction_signals: [
      ...baseWorld.prediction_signals,
      {
        ping_id: "signal-2",
        exposure_asset_id: "community-2",
        priority_score: 20,
        priority_rank: 8,
        priority_level: "low",
        state: "forecast",
      },
    ],
    community_access: [
      ...baseWorld.community_access,
      {
        community_id: "community-2",
        isolated: false,
        time_to_isolation_hours: null,
      },
    ],
  } as unknown as WorldStateSnapshot;
  const blockedHighRisk = {
    ...plan.assignment_results[0],
    route: null,
    arrival_minutes: null,
    meets_deadline: false,
    people_evacuated: 0,
  };
  const reachableLowRisk = {
    ...plan.assignment_results[0],
    community_id: "community-2",
  };
  const mixedPlan = {
    ...plan,
    assignment_results: [blockedHighRisk, reachableLowRisk],
  } as unknown as PlanResult;

  const destinations = responseDestinations(
    expandedBootstrap,
    expandedWorld,
    mixedPlan,
  );

  assert.equal(destinations[0].communityId, "community-2");
  assert.equal(destinations[0].status, "priority");
  assert.equal(destinations[1].communityId, "community-1");
  assert.equal(destinations[1].status, "blocked");
});
