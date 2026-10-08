# Policy-independent response contract

Status: **contract v1.0; release and charging-start mechanisms implemented**.

The response contract defines the boundary between a policy decision and a
hypothetical change in one state-transition channel. Its executable types are
in `src/simulation_contract.py`; the common simulator contract is `0.4.0`.

Concrete implementations are documented in `docs/release_response.md` and
`docs/arrival_response.md`.

## 1. Separation of responsibilities

```text
baseline transition model      policy layer
estimated h_0(t)               policy-defined driver d(t)
             \                  /
              response contract
          assumed theta and delay
                       |
             adjusted transition quantity
                       |
                simulator engine
          random draw and state mutation
```

The response layer:

- does not read OCPI or DATEX directly;
- does not calculate F1 or an adaptive price;
- does not calculate scarcity activation;
- does not apply `lambda`, coverage `kappa` or rollout `R_i(t)`;
- does not select treated entities;
- does not perform a stochastic transition draw;
- does not mutate station or EVSE state directly.

It consumes a final external driver already produced by the policy/adoption
layer. Therefore the same response contract can be used with different pricing
policies or with a non-price experimental signal having the same declared unit.

## 2. Contract components

`PolicyIndependentResponseContract` declares:

- contract ID and version;
- one channel ID;
- exactly one source and destination status;
- baseline transition input name and unit;
- response output name and unit;
- driver name and unit;
- functional form identity;
- named parameter definitions, units and bounds;
- expected monotonicity;
- permitted simulated outcomes;
- statuses that the mechanism is forbidden to alter.

The contract must preserve the baseline when the driver is zero. It must be
deterministic given baseline, driver, parameter values and delay. Randomness is
owned by the simulator after the response quantity has been calculated.

## 3. Runtime driver

`ResponseDriverPoint` contains only:

- entity ID;
- timezone-aware effective timestamp;
- driver name, unit and finite numeric value;
- withheld flag and reason;
- mandatory `policy_defined` provenance.

Name and unit must match the response contract exactly. A withheld policy
decision is not converted to driver value zero. It is rejected by the response
boundary and must remain explicitly withheld upstream. This prevents missing
tariffs or missing evidence from being interpreted as no behavioural effect.

For a future pricing experiment, the policy layer may eventually emit a driver
such as the final applicable rate adjustment after rollout and intensity have
been applied. That exact driver is deliberately not approved in this step.

## 4. Scenario parameters

`AssumptionDrivenResponseSpecification` binds scenario values to a contract.
Every required parameter must appear exactly once, satisfy its declared bounds
and have `assumed` provenance. Extra and missing parameters are rejected.

Delay remains an explicit non-negative scenario value. At evaluation time the
engine will use the driver effective at `t - delay`; the response contract does
not fabricate a missing historical signal.

Requested outputs must be a subset of the outcomes permitted by the contract.
An assumed model cannot widen its own claim scope.

## 5. Provenance chain

| Object | Provenance | Meaning |
| --- | --- | --- |
| Baseline transition hazard/probability | `estimated` | Derived from qualified historical transitions. |
| Driver point | `policy_defined` | Output of a policy/adoption decision, not observed behaviour. |
| Sensitivity and delay | `assumed` | Scenario variables until intervention evidence exists. |
| Adjusted transition quantity | `simulated` | Counterfactual quantity conditional on the contract and assumptions. |
| Generated transition/state | `simulated` | Result of the simulator's stochastic draw. |

No stage may relabel an assumed parameter as estimated merely because the
simulation was run repeatedly.

## 6. Safety invariants

The contract enforces:

1. zero driver produces the baseline response quantity;
2. source and destination statuses differ;
3. equipment and data-quality statuses (`outoforder`, `inoperative`, `unknown`,
   `blocked`) cannot be endpoints of the price-response channel;
4. policy and response identities remain separate;
5. parameters and drivers are finite and unit-matched;
6. withheld driver values are never silently applied;
7. response computation is deterministic and cannot mutate state;
8. allowed outputs are explicit and versioned.

## 7. Implemented channels

The generic boundary is instantiated for two observable proxy channels:

```text
charging -> available  (`release_proxy`)
available -> charging  (`charging_start_proxy`)
```

Both use exponential hazard shifts, assumed non-negative sensitivities and an
explicit delayed driver. A positive adjustment increases release hazard and
decreases accepted-start hazard. Spatial redistribution remains absent.
