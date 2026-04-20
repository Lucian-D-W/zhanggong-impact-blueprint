# Demo Script: Without Skill vs With Skill

## Without ZG Impact Blueprint

1. Open a file.
2. Guess what is affected.
3. Edit code.
4. Run whatever tests seem plausible.
5. Hope nothing important was missed.

## With ZG Impact Blueprint

1. Run `setup` once after copying the skill folder.
2. Run `analyze`.
3. Read the brief:
   - selected seed
   - direct impact
   - affected contracts
   - architecture chains
   - recommended tests
   - uncertainty/trust
4. Edit code with that scope in mind.
5. Run `finish`.
6. Review:
   - affected tests found or not
   - coverage available or unavailable
   - contract links that still need human judgment
   - remaining risk is explicit rather than implied away

## Product value

- Before edit: impact becomes visible.
- Before edit: contract-level blast radius becomes visible too.
- After edit: tests and coverage are reported honestly.
- Remaining uncertainty is shown instead of being disguised as safety.
