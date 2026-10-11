# Observability and tuning

Every recommendation is traced in LangSmith, user ratings are attached to the traces, and an
evaluation dataset measures the system. Together they make the selection logic visible and
changes to it measurable. Setup: the LangSmith variables in [Configuration](configuration.md#langsmith).

## Reading a trace

Open a trace from the app (**View trace in LangSmith** on a result or in the history) or from
the LangSmith project (`LANGSMITH_PROJECT`, default `song-recommender`).

```
recommend_song                      root run, id = the recommendation's request id
├── route_request                   heuristics; a light-model classifier call only if unsure
├── need_analyst                    ChatModel call: the full rendered prompt and the Need Profile
├── music_curator                   ChatModel call: 3 ranked candidates with rationales
├── verify_candidates
│   ├── spotify_lookup  (tool)      one per candidate: the matched track or the closest miss
│   └── …
├── [music_curator, verify_candidates]   only when nothing was verified (retry on heavy)
└── finalize
    └── youtube_lookup  (tool)
```

- **Inputs of the root run:** `user_input` (the verbatim text, after any edits),
  `input_mode`, `locale`, and `transcript` (the raw transcript, for voice input).
- **Outputs:** the recommendation, or the clarifying question if the run paused.
- **LLM runs** show the full message list sent to the model (system and user prompt, as
  rendered from the prompt file) and the raw answer. Reasoning summaries appear here when
  `LLM_HEAVY_REASONING=on` with OpenAI.
- **Catalog runs** (`spotify_lookup`, `youtube_lookup`) show what was searched and found. A
  rejected candidate's reason names the closest Spotify track and the similarity scores.

### Metadata and tags

Set when the run starts:

| Metadata | Content |
|----------|---------|
| `request_id`, `thread_id` | the recommendation id; `thread_id` groups a run and its resumed run (FR-44) |
| `resumed` | `true` for the run after a clarifying answer |
| `models`, `fallback_models` | `provider:model` per tier |
| `prompt_versions` | e.g. `{"router": "v1", "need_analyst": "v1", "curator": "v1"}` |
| `candidate_count`, `app_version` | further inputs that affect results |

Added when the run ends:

| Metadata | Content |
|----------|---------|
| `routing_complexity`, `routing_source`, `routing_reasons` | the routing decision (heuristics or classifier) and why |
| `models_used` | the model that answered, per node (e.g. a dated snapshot) |
| `escalations`, `curation_attempts` | every escalation (node, from → to tier, reason); number of curator attempts |
| `status`, `spotify_verified`, `youtube_verified` | the outcome |

| Tag | Meaning |
|-----|---------|
| `text` / `voice` | input mode |
| `locale:en` / `locale:pl` | UI language |
| `clarified` | a clarifying question was asked (and on the resumed run) |
| `escalated` | at least one escalation to the heavy tier |

Filter the project by these tags and metadata to find, for example, every escalated run, every
voice request, or every run of a given prompt version.

### Clarification threads

A request with a clarifying question has two runs: the first ends with the question, and the
resumed run (a stable id derived from the request id) continues from the checkpoint with
`clarification_question` and `clarification_answer` in its inputs. Both share `thread_id`, so
LangSmith's **Threads** view shows them as one conversation. The app's trace link points to the
run that produced the song.

## User feedback

The 👍/👎 buttons and the optional comment are stored in the app (`feedback` table) and sent to
LangSmith as feedback with the key **`user_rating`** (1 = up, 0 = down) on the run that produced
the song (FR-43).

- Rating again **replaces** the earlier rating, in the app and in LangSmith (the feedback id is
  derived from the request id).
- If LangSmith is off or unreachable, the rating is kept locally with
  `synced_to_langsmith=false`; the history shows "Saved locally". Rating again retries.
- In LangSmith, filter runs by feedback `user_rating = 0` to collect failure cases. Each is a
  candidate for the evaluation dataset.

## Running evaluations

The evaluation runs the real agent graph (real models and Spotify) on the examples in
[backend/evals/dataset.jsonl](../backend/evals/dataset.jsonl) and scores the results in a
LangSmith experiment ([ADR-10](adr/step-10-evals.md)).

```bash
cd backend
uv run python -m evals.run_evals --limit 3                    # smoke run, about 30 s
uv run python -m evals.run_evals                              # all 32 examples, 3-4 min
uv run python -m evals.run_evals --repetitions 2 --description "curator v2: situation details"
uv run python -m evals.run_evals --sync-only                  # update the LangSmith dataset only
```

| Option | Default | Meaning |
|--------|---------|---------|
| `--limit N` | all | only the first N examples of the file |
| `--repetitions N` | 1 | run every example N times; results vary between runs, so use 2 or more to compare versions |
| `--concurrency N` | 4 | examples run in parallel |
| `--judge-model provider:model` | `LLM_HEAVY` | model of the fit judge; a different provider avoids the system judging its own taste |
| `--with-youtube` | off | also look up YouTube (uses the daily quota; adds `youtube_verified`) |
| `--description TEXT` | — | what this experiment changes; shown in LangSmith |
| `--prefix TEXT` | prompt versions | experiment name prefix |
| `--dataset NAME` | `song-recommender-evals` | LangSmith dataset |

How it works:

- **Dataset sync.** The JSONL file is the source of truth. Each run makes the LangSmith dataset
  match it: new lines are created, changed ones updated, removed ones **deleted**. Add
  examples to the file, not in the LangSmith UI, or the next run removes them.
- **Isolation.** Each example runs without recommendation history (so repeats are visible), a
  clarifying question is answered automatically with the example's `clarification_answer`
  (or a generic answer), and the eval keeps its own database in `backend/evals/.data/`. The
  app's history and its LangSmith project are not touched.
- **Output.** The terminal prints the mean of every metric, the repeated songs, and links to
  the experiment and the comparison view.

### Metrics

| Metric | Meaning | Baseline (prompts v1) |
|--------|---------|------------------------|
| `completed` | a recommendation was produced | 1.00 |
| `spotify_verified` | the song was verified on Spotify | 1.00 |
| `explanation_language` | explanation and need summary in the UI language | 1.00 |
| `escalated`, `curation_attempts` | escalation rate; curator attempts | 0.00; 1.00 |
| `clarified` | a clarifying question was asked | 0.03 |
| `latency_s`, `within_15s` | end-to-end seconds; share within 15 s (NFR-3) | 16.8; 0.59 |
| `fit` | LLM judge: fit of the song, 0–1 (four aspects of 0–2, summed) | 0.83 |
| `fit_energy`, `fit_goal`, `fit_requests`, `fit_specificity` | the judge's aspects | 1.00, 0.98, 1.00, **0.33** |
| `profile_faithful` | the Need Profile reads the description correctly | 1.00 |
| `distinct_songs`, `distinct_artists` | variety across the dataset (1.0 = no repeats) | 0.84, 0.78 |

Each judge score has a comment, e.g. "7/8 (energy 2, goal 2, requests 2, specificity 1).
Weaknesses: …", followed by the reasoning. The baseline's weak point is specificity: the curator
tends to pick well-known defaults for a mood (see ADR-10).

### Comparing experiments

Experiments are named after the prompt versions (`curator-v1.need_analyst-v1.router-v1-<id>`).
Their metadata records the prompt versions, models, judge model and judge prompt version,
candidate count, app version, dataset version and git commit.

In LangSmith: **Datasets → song-recommender-evals → Experiments**. Select two or more
experiments and **Compare** to see the metric deltas and the per-example outputs side by side.

Compare like with like:

- the same dataset version, or at least the same examples;
- the same judge model and judge prompt version (a judge change makes `fit` incomparable);
- 2 or more repetitions per version, because single runs differ (diversity 0.75 vs 0.84, and
  latency 15.4 s vs 16.8 s for the same system).

## Changing a prompt

Prompts are versioned files ([FR-42](requirements.md)):

```
backend/app/agents/prompts/
  router.v1.md         complexity classifier
  need_analyst.v1.md   Agent 1: Need Profile, clarifying question
  curator.v1.md        Agent 2: candidates and explanations
backend/evals/prompts/
  fit_judge.v2.md      evaluation judge
```

A file has a `<!-- system -->` and a `<!-- user -->` section with `{{placeholders}}`. The
**highest version** of each prompt is loaded at startup and recorded on every trace.

Workflow:

1. **Find what to improve:** an eval metric (e.g. `fit_specificity`), thumbs-down traces, or
   escalations.
2. **Copy** the current file to the next version (`curator.v1.md` → `curator.v2.md`) and edit
   it. Keep the placeholders; `uv run pytest tests/test_prompts.py` checks that the shipped
   prompts use exactly the expected ones.
3. **Run the evaluation** with `--repetitions 2 --description "what changed"`, plus a baseline
   with the old version if there is no recent one.
4. **Compare** the experiments in LangSmith. Also look at the per-example outputs of the cases
   you meant to fix, and at the cases that got worse.
5. **Keep or drop:** commit the new file (and add an ADR when it is a lasting decision, see
   [docs/adr/README.md](adr/README.md)), or delete it to go back to the previous version.

Other levers, each recorded in the experiment metadata:

| Lever | Where |
|-------|-------|
| Models per tier, fallbacks, reasoning | `.env`: `LLM_LIGHT`, `LLM_HEAVY`, `LLM_*_FALLBACK`, `LLM_HEAVY_REASONING` |
| Routing thresholds and contrast markers | [backend/app/llm/routing.py](../backend/app/llm/routing.py) |
| Candidates per curator attempt (3) | `CANDIDATE_COUNT` in [backend/app/agents/state.py](../backend/app/agents/state.py) |
| Catalog matching threshold (85) | `MATCH_THRESHOLD` in [backend/app/music/matching.py](../backend/app/music/matching.py) |

To evaluate the judge itself, re-score stored outputs before running a full experiment (as
done in ADR-10), and change the judge prompt version whenever its wording or scale changes.
