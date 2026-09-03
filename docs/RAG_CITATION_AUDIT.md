# RAG Citation Audit

- Aggregate cite_precision: `0.841`
- Aggregate cite_paper_precision: `0.904`
- Low precision rows: `10`

## Low Precision Items

### `g023` compare

- Question: How does FLARE differ from Self-RAG in retrieval timing?
- cite_precision: `0.0`
- cite_paper_precision: `0.0`
- retrieval labels: `['ba00ad89ffb8a057b0c6', 'b4dfad46af2b4a32a44a']`
- citation labels: `['ba00ad89ffb8a057b0c6', 'b4dfad46af2b4a32a44a']`

| Citation | Paper | Section | Rank | Match | Diagnosis |
|---|---|---|---:|---|---|
| `557f51d7c7b01f03b7b7` | `arxiv:2312.10997` | `AUGMENTATION PROCESS IN RAG` | `3` | no | `wrong_paper_or_unknown_chunk` |

### `g032` evaluation

- Question: Why is citation checking useful for hallucination control?
- cite_precision: `0.0`
- cite_paper_precision: `1.0`
- retrieval labels: `['17cf8a553be34612098c', '7e42f21c2fdadc8830d3']`
- citation labels: `['17cf8a553be34612098c', '7e42f21c2fdadc8830d3']`

| Citation | Paper | Section | Rank | Match | Diagnosis |
|---|---|---|---:|---|---|
| `aef84540b468c11934f0` | `arxiv:2401.01313` | `None` | `12` | no | `right_paper_wrong_chunk` |

### `g038` method

- Question: How does dense retrieval relate to contrastive learning?
- cite_precision: `0.0`
- cite_paper_precision: `0.0`
- retrieval labels: `['e3ac344b4bf32f5c4da9', '4fc8deabd11b4f817d2b']`
- citation labels: `['e3ac344b4bf32f5c4da9', '4fc8deabd11b4f817d2b']`

| Citation | Paper | Section | Rank | Match | Diagnosis |
|---|---|---|---:|---|---|
| `95b5d4e27624d8e0492e` | `arxiv:2310.11511` | `None` | `5` | no | `wrong_paper_or_unknown_chunk` |

### `g045` compare

- Question: How do reranking and citation validation solve different RAG problems?
- cite_precision: `0.0`
- cite_paper_precision: `0.0`
- retrieval labels: `['4fc8deabd11b4f817d2b', '92006f8f61e8c37a71ff']`
- citation labels: `['4fc8deabd11b4f817d2b', '92006f8f61e8c37a71ff']`

| Citation | Paper | Section | Rank | Match | Diagnosis |
|---|---|---|---:|---|---|
| `b80deab4623a992f3770` | `arxiv:2104.08663` | `None` | `14` | no | `wrong_paper_or_unknown_chunk` |
| `010267dfe466cdb683c8` | `arxiv:2310.11511` | `MAIN RESULTS` | `12` | no | `wrong_paper_or_unknown_chunk` |

### `g033` compare

- Question: Compare original RAG and the RAG survey view of modern RAG systems.
- cite_precision: `0.3333333333333333`
- cite_paper_precision: `0.6666666666666666`
- retrieval labels: `['92a77f6de4ec7c29df1e', '652daeb9cc13bb92ce77']`
- citation labels: `['92a77f6de4ec7c29df1e', '652daeb9cc13bb92ce77', 'dba2caabdee577fcecd4', '05f396ba337cf45342dc']`

| Citation | Paper | Section | Rank | Match | Diagnosis |
|---|---|---|---:|---|---|
| `dba2caabdee577fcecd4` | `arxiv:2005.11401` | `Abstract` | `2` | yes | `direct_support` |
| `f030c8b540e8ad9b8588` | `arxiv:2312.10997` | `Abstract` | `11` | no | `right_paper_wrong_chunk` |
| `05e56a782241bc06cfd5` | `arxiv:2310.11511` | `INTRODUCTION` | `12` | no | `wrong_paper_or_unknown_chunk` |

### `g012` method

- Question: How does RAG use DPR or dense retrieval?
- cite_precision: `0.5`
- cite_paper_precision: `1.0`
- retrieval labels: `['bf63b5b3ac917844b268', '563088608864d1932716']`
- citation labels: `['bf63b5b3ac917844b268', '563088608864d1932716']`

| Citation | Paper | Section | Rank | Match | Diagnosis |
|---|---|---|---:|---|---|
| `563088608864d1932716` | `arxiv:2005.11401` | `Methods` | `3` | yes | `direct_support` |
| `71596e68b133389e121a` | `arxiv:2005.11401` | `None` | `13` | no | `right_paper_wrong_chunk` |

### `g021` factual

- Question: What is Active Retrieval Augmented Generation in FLARE?
- cite_precision: `0.5`
- cite_paper_precision: `0.5`
- retrieval labels: `['b44194319bbaaecc23ed', '92478cfec36da0be0a5e']`
- citation labels: `['b44194319bbaaecc23ed', '92478cfec36da0be0a5e']`

| Citation | Paper | Section | Rank | Match | Diagnosis |
|---|---|---|---:|---|---|
| `92478cfec36da0be0a5e` | `arxiv:2305.06983` | `Abstract` | `1` | yes | `direct_support` |
| `f9957f6bc6b8c8bdcbba` | `arxiv:2312.10997` | `AUGMENTATION PROCESS IN RAG` | `3` | no | `wrong_paper_or_unknown_chunk` |

### `g022` method

- Question: How does FLARE decide when and what to retrieve?
- cite_precision: `0.5`
- cite_paper_precision: `1.0`
- retrieval labels: `['92478cfec36da0be0a5e', 'f8e7f2853fe1a1bf194b']`
- citation labels: `['92478cfec36da0be0a5e', 'f8e7f2853fe1a1bf194b']`

| Citation | Paper | Section | Rank | Match | Diagnosis |
|---|---|---|---:|---|---|
| `92478cfec36da0be0a5e` | `arxiv:2305.06983` | `Abstract` | `1` | yes | `direct_support` |
| `b2c5c3e39aff829287a1` | `arxiv:2305.06983` | `Direct FLARE` | `2` | no | `right_paper_wrong_chunk` |

### `g024` method

- Question: Why is FLARE considered an iterative retrieval method?
- cite_precision: `0.5`
- cite_paper_precision: `0.5`
- retrieval labels: `['92478cfec36da0be0a5e', 'cace2754227fbe5e2b57']`
- citation labels: `['92478cfec36da0be0a5e', 'cace2754227fbe5e2b57', '5921e877e6304984b12d']`

| Citation | Paper | Section | Rank | Match | Diagnosis |
|---|---|---|---:|---|---|
| `5921e877e6304984b12d` | `arxiv:2305.06983` | `References` | `7` | yes | `direct_support` |
| `557f51d7c7b01f03b7b7` | `arxiv:2312.10997` | `AUGMENTATION PROCESS IN RAG` | `3` | no | `wrong_paper_or_unknown_chunk` |

### `g042` method

- Question: Why can one-shot retrieval be insufficient for complex RAG questions?
- cite_precision: `0.6666666666666666`
- cite_paper_precision: `1.0`
- retrieval labels: `['a670ce4451b873daf287', '9a10815a6e55f9d72e33']`
- citation labels: `['a670ce4451b873daf287', '9a10815a6e55f9d72e33', '2f5b02305e8a44643ccb']`

| Citation | Paper | Section | Rank | Match | Diagnosis |
|---|---|---|---:|---|---|
| `2f5b02305e8a44643ccb` | `arxiv:2312.10997` | `TASK AND EVALUATION` | `8` | yes | `direct_support` |
| `a670ce4451b873daf287` | `arxiv:2305.06983` | `None` | `3` | yes | `direct_support` |
| `8d635f19e243979f18ed` | `arxiv:2312.10997` | `DISCUSSION AND FUTURE PROSPECTS` | `1` | no | `right_paper_wrong_chunk` |
