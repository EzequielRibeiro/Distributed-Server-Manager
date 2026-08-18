#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from core.network.agent_inspection import (
    AgentPortInspectionRequest,
    AgentPortInspectionResponse,
    validate_agent_response,
)


class AgentInspectionTest(unittest.TestCase):
    def test_matching_response_is_accepted(self):
        request = AgentPortInspectionRequest(
            agent_id="agent-demo",
            node_id="node-demo",
            protocol="udp",
            start_port=24000,
            end_port=24999,
        )

        response = AgentPortInspectionResponse(
            agent_id="agent-demo",
            node_id="node-demo",
            protocol="udp",
            occupied_ports=frozenset({24000, 27000}),
            source="agent",
        )

        result = validate_agent_response(request, response)

        self.assertEqual(result, {24000})


if __name__ == "__main__":
    unittest.main()
