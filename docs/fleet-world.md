# Fleet world

The home is a four-island archipelago. Each named island is a Mac mini slot:

| Island | Slot ID | Source wing profile |
| --- | --- | --- |
| Mac Coding 01 | `mac-coding-1` | `node-coding` |
| Mac Coding 02 | `mac-coding-2` | `node-coding` |
| Mac Creative | `mac-creative` | `node-design` |
| Mac Marketing | `mac-marketing` | `node-marketing` |

Select an island to enter its town. Walk with WASD or arrows, switch among the seven crew members with keys 1–7, and press E near a station. Open Chart to see the fleet together and use WASD to explore the surrounding sea. Enter town returns to the selected island. Touch controls provide the same movement on smaller screens.

Configured means that the explicit instance inventory assigns a device to a slot. Planned means the slot has no registered device. Template is the public source topology. These labels do not certify installation, connectivity, CPU usage or a running job.

Observed work requires a recent record for the selected tenant and exact machine. Unattributed records cannot supply work presence. Expired, future, canceled or disconnected evidence clears the signal. Local character control and the crew tour are labeled exploration/demonstration. Brand parcels show the shared portfolio; device placement remains unassigned unless a source explicitly records it.

The frontend projects inventory and activity through the existing local read-only snapshot. It adds no device commands. Instance inventory and receipts remain in the private data checkout. Public snapshots contain source templates and omit private machine identifiers.

The existing one-host-per-wing inventory continues to assign Coding 01, Creative and Marketing. To register a second coding machine, the private inventory can include an explicit canonical slot entry:

```yaml
islands:
  mac-coding-2:
    wing: coding
    hostname: example-coding-two
```

Its private `nodes/islands/mac-coding-2/node.yaml` must contain the same `wing` and `hostname`. Explicit slot entries take priority over the legacy wing assignment; missing or mismatched profiles remain Planned. Every configured slot must have a unique hostname. This example defines a source contract; it performs no enrollment or device action.

An invalid entire `islands` map—unknown slot keys, a non-map value or more than four entries—holds assignments as Planned with a `fleet_islands_held` warning. An invalid entry holds only that explicitly named slot.

One detailed town and one renderer are retained. The other fleet islands use distant silhouettes. Deterministic scenery chunks recycle as the chart moves; unnamed islets are scenery, not additional machines. Eco and Balanced retain the existing resolution, frame-rate and shadow limits. The geometry budget is 35,000 triangles for the environment and archipelago together, with at most 40 additional archipelago submissions.
