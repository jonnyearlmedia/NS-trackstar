# Answerability fixtures

A project card is a failure when a normal person reads it and still cannot say what is
happening. These fixtures pin that down per project, for the ten Vallejo projects named
in the coverage contract and a representative project in every other jurisdiction.

Each entry lists, per project, the assertion fields, status dimensions, event kinds and
typed relationships Trackstar must hold in order to answer the nine questions:

1. what is this
2. current status
3. latest meaningful change
4. next known step
5. useful scale
6. exact or defensible location
7. important related projects
8. official evidence
9. source freshness

Two different checks consume this file, and the split matters.

`services/api/tests/test_answerability.py` proves the *composer* turns that evidence
shape into a real consumer answer. It builds evidence from the declared field names with
neutral placeholder values, so nothing in this repository asserts a fact about a real
project that Trackstar has not collected.

`apps/web/src/app/api/status/answerability/route.ts` proves *production* actually holds
that evidence, by reading the deployed project detail. That is the check that fails when
a collector goes stale and a real card starts degrading toward generic copy.
