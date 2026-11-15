# Feedback on Nebius Token Factory and NVIDIA Nemotron

From the team behind **Inherit** ([TEAM MEMBER NAMES]), Nebius x NVIDIA Global AI Hackathon, Coding & Agentic Engineering track.

*Replace each `[PLACEHOLDER]` and delete the notes in italics. Keep only points you actually experienced.*

## Summary
[ONE OR TWO SENTENCES: OVERALL EXPERIENCE]

## Getting access
- **Billing blocked us at sign-up.** Opening Token Factory took us straight to a billing page. Adding a card failed with Stripe's "Your card does not support this type of purchase." We had no other card, so we couldn't make API calls for [HOW LONG].
- **Suggestion:** for hackathon participants, offer credits without a card (for example, a code tied to the registered email), or accept more card and payment types. A clearer error message saying *which* card types work would also help.
- **How it was resolved:** [HOW YOU EVENTUALLY GOT ACCESS, OR "NOT RESOLVED BEFORE THE DEADLINE"].

## API and developer experience
*Fill in after real calls.*
- **OpenAI compatibility:** worked as expected with the `openai` Python client: [YES / ISSUES].
- **Finding model IDs and the base URL:** [EASY / HARD; WHERE YOU FOUND THEM].
- **Rate limits and errors:** [ANY 429s, TIMEOUTS, UNCLEAR ERRORS].
- **Latency:** reasoner [N] s, worker [N] s per call (see *Model usage* in our reports).

## Nemotron models
*Fill in after real calls.*
- **Structured JSON output** (diagnosis schema, input lists): [HOW RELIABLE; HOW OFTEN OUR ONE REPAIR RETRY WAS NEEDED].
- **Code diagnosis quality:** [DID IT FIND THE SHARED-STATE CAUSE; WERE PATCHES CORRECT].
- **Small model for high-volume input generation:** [QUALITY / SPEED].
- **What would help:** [E.G. A JSON MODE, LONGER CONTEXT, CLEARER MODEL CARDS].

## Documentation
- [WHAT WAS CLEAR]
- [WHAT WAS MISSING OR CONFUSING]

## Hackathon organisation
- [ANY FEEDBACK ON RULES, COMMUNICATION, DISCORD, DEADLINES]
