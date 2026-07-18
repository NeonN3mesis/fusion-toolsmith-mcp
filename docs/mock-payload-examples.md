# Mock Payload Examples

These examples are stable no-Fusion payloads returned by `fusion-mcp mock-server`.
They are intended for client integration tests and docs. They demonstrate shape only:
mock mode never reads, writes, or edits a Fusion design.

## `inspect_analysis_capabilities`

Arguments:

```json
{}
```

Response payload:

```json
{
  "result": {
    "arguments": {},
    "blockingReasons": [
      "Mock mode has no real Fusion BRep or measure-manager APIs."
    ],
    "broadPhaseAvailable": true,
    "exactInterference": {
      "booleanCandidate": {
        "available": false,
        "method": null
      },
      "copyCandidate": {
        "available": false,
        "method": null
      },
      "status": "unsupported",
      "supported": false,
      "temporaryBRepManagerAvailable": false
    },
    "exactMinimumDistance": {
      "distanceCandidate": {
        "available": false,
        "method": null
      },
      "measureManagerAvailable": false,
      "status": "unsupported",
      "supported": false
    },
    "mock": true,
    "readOnly": true,
    "tool": "inspect_analysis_capabilities",
    "visibleBodyCount": 2,
    "warnings": [
      "Mock mode does not run exact analysis."
    ]
  }
}
```

## `plan_surface_repair`

Arguments:

```json
{
  "body_name": "Mock Surface",
  "edge_entity_tokens": [
    "edge-token"
  ],
  "operation": "stitch_surfaces",
  "reason": "docs example"
}
```

Response payload:

```json
{
  "result": {
    "arguments": {
      "body_name": "Mock Surface",
      "edge_entity_tokens": [
        "edge-token"
      ],
      "operation": "stitch_surfaces",
      "reason": "docs example"
    },
    "blockingReasons": [],
    "edgeEntityTokens": [
      "edge-token"
    ],
    "faceEntityTokens": [],
    "inspection": {
      "surfaceBodyCount": 1,
      "warnings": [
        "Mock mode does not inspect real surface topology."
      ]
    },
    "mock": true,
    "okToProceed": true,
    "operation": "stitch_surfaces",
    "parameters": {},
    "readOnly": true,
    "reason": "docs example",
    "riskLevel": "medium",
    "target": {
      "bodyName": "Mock Surface",
      "classification": "surface",
      "entityToken": null
    },
    "tool": "plan_surface_repair",
    "warnings": [
      "Mock mode plans surface repair but does not modify Fusion geometry."
    ]
  }
}
```

## `create_revolute_joint`

Arguments:

```json
{
  "motion_axis": "z",
  "name": "Mock Hinge",
  "point_one_name": "Point A",
  "point_two_name": "Point B"
}
```

Response payload:

```json
{
  "result": {
    "arguments": {
      "motion_axis": "z",
      "name": "Mock Hinge",
      "point_one_name": "Point A",
      "point_two_name": "Point B"
    },
    "jointKind": "revolute",
    "jointName": "Mock Hinge",
    "mock": true,
    "motionAxis": "z",
    "normalDirection": null,
    "note": "Mock mode does not create Fusion assembly joints.",
    "pointOneName": "Point A",
    "pointTwoName": "Point B",
    "slideDirection": null,
    "stateComparison": {
      "hasChanges": true,
      "riskLevel": "low"
    },
    "tool": "create_revolute_joint"
  }
}
```

## `plan_manufacturing_operation`

Arguments:

```json
{
  "feeds": {
    "cut": 500
  },
  "machine": {
    "name": "Shop Mill"
  },
  "operation_name": "Adaptive1",
  "operation_type": "adaptive",
  "post_processor": {
    "name": "generic"
  },
  "requires_user_approval": true,
  "setup_name": "Setup1",
  "speeds": {
    "rpm": 12000
  },
  "stock": {
    "material": "6061"
  },
  "tool": {
    "name": "6mm flat"
  },
  "wcs": {
    "origin": "stock"
  }
}
```

Response payload:

```json
{
  "result": {
    "arguments": {
      "feeds": {
        "cut": 500
      },
      "machine": {
        "name": "Shop Mill"
      },
      "operation_name": "Adaptive1",
      "operation_type": "adaptive",
      "post_processor": {
        "name": "generic"
      },
      "requires_user_approval": true,
      "setup_name": "Setup1",
      "speeds": {
        "rpm": 12000
      },
      "stock": {
        "material": "6061"
      },
      "tool": {
        "name": "6mm flat"
      },
      "wcs": {
        "origin": "stock"
      }
    },
    "blockingReasons": [],
    "mock": true,
    "okToProceed": true,
    "operation": {
      "feeds": {
        "cut": 500
      },
      "name": "Adaptive1",
      "speeds": {
        "rpm": 12000
      },
      "tool": {
        "name": "6mm flat"
      },
      "type": "adaptive"
    },
    "postProcessor": {
      "name": "generic"
    },
    "readOnly": true,
    "requiresUserApproval": true,
    "riskLevel": "medium",
    "setup": {
      "machine": {
        "name": "Shop Mill"
      },
      "name": "Setup1",
      "stock": {
        "material": "6061"
      },
      "wcs": {
        "origin": "stock"
      }
    },
    "tool": "plan_manufacturing_operation",
    "warnings": [
      "Mock mode plans manufacturing data but does not create setups, generate toolpaths, or post-process output."
    ],
    "workspace": {
      "okToInspectSetups": true,
      "workspaceAvailable": true
    }
  }
}
```

## `revolve_feature`

Arguments:

```json
{
  "body_name": "Mock Revolve Body",
  "name": "Mock Revolve"
}
```

Response payload:

```json
{
  "result": {
    "arguments": {
      "body_name": "Mock Revolve Body",
      "name": "Mock Revolve"
    },
    "bodyName": "Mock Revolve Body",
    "created": true,
    "createdBodies": [
      "Mock Revolve Body"
    ],
    "featureName": "Mock Revolve",
    "mock": true,
    "name": "Mock Revolve",
    "note": "Mock mode does not edit Fusion geometry.",
    "stateComparison": {
      "hasChanges": true,
      "riskLevel": "low"
    },
    "targetBody": "Mock Revolve Body",
    "tool": "revolve_feature"
  }
}
```
