# RAG Claim Eval Report

- Dataset: `tests/eval/qa_set.claims.jsonl`
- Items: `40`

## Aggregate

| Metric | Value |
|---|---:|
| `claim_recall` | `0.811` |
| `grounded_claim_recall` | `0.722` |
| `no_answer_success_rate` | `1.0` |
| `forbidden_claim_violations` | `0` |
| `errors` | `0` |
| `n_claim_labeled` | `30` |
| `n_no_answer` | `10` |
| `claim_label_coverage` | `0.75` |
| `elapsed_sec` | `178.0` |
| `n_items` | `40` |

## Gate

| Metric | Value | Rule | Status |
|---|---:|---|---|
| `claim_recall` | `0.811` | `{'min': 0.8}` | PASS |
| `grounded_claim_recall` | `0.722` | `{'min': 0.65}` | PASS |
| `no_answer_success_rate` | `1.0` | `{'min': 0.9}` | PASS |
| `forbidden_claim_violations` | `0` | `{'max': 0}` | PASS |
| `errors` | `0` | `{'max': 0}` | PASS |

## Low Claim Recall Items

### `cl029` factual

- Question: What are intrinsic and extrinsic hallucinations?
- claim_recall: `0.0`
- grounded_claim_recall: `0.0`

| Missing Claim | Text |
|---|---|
| `cl029.1` | Intrinsic hallucinations contradict source content. |
| `cl029.2` | Extrinsic hallucinations are not verifiable from the source. |
| `cl029.3` | The distinction is about relationship to source evidence. |

### `cl006` evaluation

- Question: What tasks does Self-RAG evaluate on?
- claim_recall: `0.3333333333333333`
- grounded_claim_recall: `0.3333333333333333`

| Missing Claim | Text |
|---|---|
| `cl006.2` | Self-RAG reports open-domain QA benchmarks such as PopQA or TriviaQA. |
| `cl006.3` | Self-RAG includes long-form or factuality-oriented tasks such as ASQA, PubHealth, or biography generation. |

### `cl011` evaluation

- Question: Which open-domain QA datasets does the original RAG paper use?
- claim_recall: `0.3333333333333333`
- grounded_claim_recall: `0.3333333333333333`

| Missing Claim | Text |
|---|---|
| `cl011.1` | The paper uses Natural Questions. |
| `cl011.2` | The paper uses TriviaQA or WebQuestions. |

### `cl019` evaluation

- Question: Why is recall important in the retrieval stage of RAG?
- claim_recall: `0.3333333333333333`
- grounded_claim_recall: `0.3333333333333333`

| Missing Claim | Text |
|---|---|
| `cl019.2` | If retrieval misses evidence, later stages cannot use it. |
| `cl019.3` | Generation quality depends on having the right context. |

### `cl024` method

- Question: Why is FLARE considered an iterative retrieval method?
- claim_recall: `0.3333333333333333`
- grounded_claim_recall: `0.3333333333333333`

| Missing Claim | Text |
|---|---|
| `cl024.2` | Retrieval happens while generation proceeds. |
| `cl024.3` | It is not just a single retrieval at the beginning. |

### `cl002` method

- Question: How does Self-RAG decide when to retrieve at inference time?
- claim_recall: `0.6666666666666666`
- grounded_claim_recall: `0.6666666666666666`

| Missing Claim | Text |
|---|---|
| `cl002.3` | External evidence is retrieved when useful or necessary. |

### `cl012` method

- Question: How does RAG use DPR or dense retrieval?
- claim_recall: `0.6666666666666666`
- grounded_claim_recall: `0.6666666666666666`

| Missing Claim | Text |
|---|---|
| `cl012.3` | The passages are retrieved from non-parametric memory. |

### `cl013` evaluation

- Question: Why does the original RAG paper discuss factuality in generation?
- claim_recall: `0.6666666666666666`
- grounded_claim_recall: `0.6666666666666666`

| Missing Claim | Text |
|---|---|
| `cl013.1` | Retrieved evidence helps ground generation. |

### `cl017` method

- Question: What is reranking in RAG and why use it?
- claim_recall: `0.6666666666666666`
- grounded_claim_recall: `0.6666666666666666`

| Missing Claim | Text |
|---|---|
| `cl017.3` | Reranking improves top evidence precision or relevance. |

### `cl028` method

- Question: How does BEIR motivate hybrid retrieval in this project?
- claim_recall: `0.6666666666666666`
- grounded_claim_recall: `0.3333333333333333`

| Missing Claim | Text |
|---|---|
| `cl028.1` | BEIR shows sparse baselines remain strong. |

### `cl030` method

- Question: How can retrieval augmentation mitigate hallucinations?
- claim_recall: `0.6666666666666666`
- grounded_claim_recall: `0.6666666666666666`

| Missing Claim | Text |
|---|---|
| `cl030.2` | Evidence grounds generation. |

