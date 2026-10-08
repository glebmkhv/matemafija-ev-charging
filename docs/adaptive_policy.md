# OSA-v1 adaptive policy

Status: **approved MVP policy, implemented v1.0.0**.

`Observable Scarcity Adjustment` (`OSA-v1`) replaces the colleague prototype's
unobserved queue length and post-charge idle time with reconstructed OCPI
capacity evidence. The implementation is `src/adaptive_policy.py`.

OSA-v1 calculates a raw adaptive adjustment. It does not yet compose that
adjustment with F1, lambda or rollout, and it does not invoke the response
model. Those connections belong to project step 10.

## 1. Inputs

At each site snapshot:

```text
A_i(t) = available_evse_count / effective_operational_capacity
C_i(t) = 1 - A_i(t)
```

`C_i(t)` is observable operational capacity pressure. It is not queue length,
rejected demand or waiting time.

The persistence input `D_i(t)` is reconstructed as the elapsed lower-bound time
since the first consecutive snapshot satisfying all of the following:

- eligible capacity evidence;
- `C_i(t) > C_trigger`;
- at least one EVSE is `charging`;
- equipment unavailability does not exceed the guard;
- no collection gap larger than twice the expected cadence.

The duration resets to zero on a gap, an ineligible snapshot or a failed
condition. It is therefore observed/reconstructed scarcity persistence, not
assumed vehicle idle time.

## 2. Signal and adjustment

Normalized pressure:

```text
P_i(t) = clip((C_i(t) - C_trigger) / (1 - C_trigger), 0, 1)
```

Persistence after grace:

```text
R_i(t) = clip((D_i(t) - T_grace) / T_ramp, 0, 1)
```

Scarcity signal and raw adjustment:

```text
S_i(t) = P_i(t)^gamma * R_i(t)
delta_p_raw(i,t) = delta_p_max * S_i(t)
```

Consequently:

- adjustment is zero throughout the grace period;
- pressure and persistence can only increase the adjustment;
- `0 <= S_i(t) <= 1`;
- `0 <= delta_p_raw <= delta_p_max`.

## 3. MVP parameter values

| Parameter | Value | Role |
| --- | ---: | --- |
| `C_trigger` | `0.50` | Begin considering scarcity above 50% operational pressure. |
| `T_grace` | `15 min` | No adjustment during the initial sustained condition. |
| `T_ramp` | `30 min` | Time after grace to reach full persistence weight. |
| `gamma` | `1.2` | Nonlinear emphasis on stronger pressure. |
| `delta_p_max` | `0.05 EUR/min` | Prototype raw-adjustment cap. |
| Minimum observation coverage | `0.80` | Data-quality gate. |
| Maximum equipment-unavailability ratio | `0.50` | Avoid pricing equipment-dominated scarcity. |

These are versioned policy parameters for stress testing, not empirically
optimal Vilnius values. The future experiment grid may vary the cap while
retaining the OSA-v1 form.

## 4. Decision states

Every evaluation returns exactly one status.

### `active`

All quality and applicability gates pass and the calculated adjustment is
positive.

### `inactive`

Evidence is valid, but adjustment is legitimately zero, for example:

- pressure is at or below the trigger;
- grace/ramp has not produced a positive signal;
- no charging EVSE can participate in the release channel.

### `withheld`

The policy cannot make a valid decision:

- F1 tariff is unavailable;
- capacity evidence is ineligible;
- effective operational capacity is zero;
- equipment loss exceeds the guard.

A withheld decision contains no adjustment value. It is never converted into
zero, because zero means a valid policy decision not to adjust.

## 5. Relationship to the original proposal

| Original prototype concept | OSA-v1 replacement |
| --- | --- |
| Assumed queue `Q` | Observed operational scarcity ratio `C_i(t)` |
| Post-charge idle time | Reconstructed duration of sustained capacity pressure |
| 15-minute grace | Retained as `T_grace` |
| Nonlinear penalty | Retained through `gamma` |
| Monetary scale | Bounded by `delta_p_max` |
| Unlimited increase | Explicit cap |

The policy therefore preserves the intended adaptive logic without claiming
variables that OCPI/DATEX do not observe.

## 6. Historical calibration

OSA-v1 deliberately does not require a statistically qualified historical
profile. This allows transparent observed-path demonstration with the current
short collection window.

A later `OSA-v2` may normalize pressure against a qualified station × local
hour × weekday/weekend baseline. That extension must not be silently introduced
into v1 and must address the risk of treating chronic infrastructure shortage
as normal.

## 7. Claim boundary

OSA-v1 can show when and by how much the pricing mechanism would adjust a rate.
It cannot show that a driver would leave earlier. Behavioural consequences are
handled separately by the assumed release response and remain
scenario-conditional.
