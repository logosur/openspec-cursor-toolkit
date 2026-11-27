# How much a cached token counts toward the usage limit (task 1.7)

Run of `evidence/cache_weights.py` on 2026-11-27, on one developer machine. Accounts are labelled A1 to A4; nothing here names a project, a session or a person.

## Answer

| Weight, in units of one cache-write token | Central | Range | How firm |
|---|---|---|---|
| Cache read | **0.02** | 0 to 0.05 | Firm that it is small: every pooled fit rejects 0.05 and above. Whether it is 0 or 0.03 is not settled |
| Cache write | 1 | (the unit) | The only class whose coefficient is above zero in every resample |
| Output | 1 | 0 to 3 | Weak: output moves together with cache writes |
| Fresh input | not separable | — | Main-call fresh input is 0.001 % of the tokens; it only counts requests |

- **A cache-read token weighs about a fiftieth of a cache-write token.** The API price ratio (0.1 against 1.25, that is 0.08) does not describe the limit on this data: the pooled fits reject it.
- **Weights relative to fresh input cannot be given.** The only large uncached input is the input of advisor sub-calls; against it a cache write weighs 1.6 to 2.6 with a range of about 1 to 17, which is too wide to use.
- **What this is enough for.** The go/no-go of D15 uses a share (the rule's saving over the supervisors' flow). A share needs relative weights only, and fresh input is too small to move it. So the simulator's weighted figures are set as `fresh 1, cache read 0.02, cache write 1, output 1`, and reported again at the ends of the range. The weighted leverage of D11, which compares pool tokens with main-model tokens, uses the same units and carries the same range.
- **Size of one soft wake, as an order of magnitude.** A soft supervisor wake reads about 1.4 million tokens, nearly all of them from the cache (`what-if.md`). At the central weights that is about 42,000 cache-write tokens, or about 0.2 points of the 5-hour window of the reference account (0.05 to 0.4 across the range). Raw token counts overstate a wake by a factor of about 30.

## Data

- Usage snapshots: 267 results of the session tool that reports plan usage, found in the transcripts, from 2026-11-14 01:02 to 2026-11-27 04:21 UTC. Each carries the plan, the 5-hour window, the weekly window for all models and the weekly window of one model family, as whole percentages with their reset times.
- Tokens: 107,824 assistant messages of 2,775 transcripts in the same days, each counted once. In millions: cache read 22,767; cache write 567; output 89; advisor input 139; fresh 0.23.
- Accounts, told apart by plan and by the phase of the weekly reset: A1 (58 snapshots), A2 (20), A3 (101), A4 (88). Three plan sizes; each account gets its own scale in the joint fits.
- Intervals: two adjacent snapshots of the same account, at most 3 hours apart, with the same window reset time. 5-hour window: 163 intervals (A1 has none). Weekly, all models: 219. Weekly, one family: 144.

## Method

1. For each interval, the tokens of the messages inside it are summed by class and by model family.
2. `change in percentage = account scale × Σ coefficient × tokens`, with non-negative coefficients (exact non-negative least squares) and one scale per account, fitted by alternating least squares.
3. The same fit is repeated on subsets: each account alone, intervals dominated by one model family, desktop-app sessions only, with a term proportional to elapsed time, and intervals merged until they span 4 percentage points.
4. Ranges come from a bootstrap over intervals, 2,000 resamples, stratified by account. The cache-read weight is also profiled: it is forced to `w` times the cache-write coefficient and the likelihood-ratio statistic `n ln(RSS / RSS_min)` is read against 3.84.

## Results

| Fit | Intervals | R² | Cache read ÷ cache write | Output ÷ cache write |
|---|---|---|---|---|
| 5-hour window, all accounts | 163 | 0.96 | 0.0001 (0 to 0.029) | 0 (0 to 0.95) |
| 5-hour window, merged intervals | 92 | 0.96 | 0 (0 to 0.024) | 0 (0 to 0.36) |
| Weekly, all models, all accounts | 219 | 0.94 | 0.005 (0 to 0.019) | 0 (0 to 2.5) |
| Weekly, one model family, its own tokens | 144 | 0.96 | 0.031 (0.021 to 0.045) | 1.9 (0.95 to 2.6) |
| 5-hour window, intervals dominated by another family | 37 | 0.98 | 0.085 (0 to 0.50) | 0.5 (0 to 73) |

Profile of the cache-read weight (likelihood-ratio statistic; above 3.84 is rejected at 95 %):

| `w` | 0 | 0.01 | 0.02 | 0.03 | 0.05 | 0.1 | 0.5 |
|---|---|---|---|---|---|---|---|
| 5-hour window, families pooled | 0 | 0.6 | 2.3 | 5.4 | 19.7 | 48.5 | 84.9 |
| 5-hour window, one coefficient set per family group | 86.2 | 25.8 | 0 | 5.2 | 46.0 | 110.9 | 170.7 |
| Weekly, one coefficient set per family group | 37.3 | 6.3 | 0 | 10.0 | 43.8 | 102.3 | 172.5 |

- With one coefficient set per family group the data picks 0.02 and rejects both 0 and 0.05. With the families pooled it cannot tell 0 from 0.02. The window of a single family gives 0.02 to 0.045. Hence "0.02, range 0 to 0.05".
- The 37 intervals dominated by one other family allow up to 0.15. They are few and their range is wide; the simulator's report carries that value as an outer sensitivity, not as part of the range.
- Fixed weight schemes against the free fit (difference in AIC, pooled 5-hour fit): all tokens equal +91; API prices +41; cache read free +43; read 0.02, write 1, output 5: +30. None beats the free fit; "all tokens equal" is the worst.
- Coefficients of the pooled 5-hour fit for the reference account, in percentage points per million tokens: cache write 4.6 (3.6 to 5.7); cache read 0.0005 (0 to 0.13); output 0 (0 to 4.2); advisor input 1.8 (0 to 4.3).

## Limits

- Percentages are whole numbers: the difference of two is off by about 0.4 points, which is large next to the few points an interval spans. The residual of the 5-hour fits is 3.6 points.
- Usage of the same accounts from other machines, cloud sessions and the chat app is not in the transcripts. It is noise, or bias where it moves with the activity seen here.
- An account switch with no snapshot of the other account in between is not detected. Two accounts with the same plan and weekly reset time would be merged.
- Cache reads are 96 % of all tokens and move with every other class; cache writes hold the previous turn's output, so those two classes are nearly collinear. That is why the output weight is the least reliable figure.
- Cache writes of the two lifetimes (5 minutes and 1 hour) are pooled. Model families are pooled except where the table says otherwise; the supervisors run on families that the single-family window does not cover.
- The residuals of adjacent intervals are not independent, so the 95 % readings are a rough guide.
- One machine, two weeks. Task 7.2 checks these weights again during the shadow week, if there is one.

## Reproduce

```
python3 evidence/cache_weights.py --since 2026-11-14 --bootstrap 2000 --seed 1
```

The script reads the transcripts and writes nothing unless `--json` or `--cache` is given. Its output labels the accounts A1 to A4 and prints no id, path or text.
