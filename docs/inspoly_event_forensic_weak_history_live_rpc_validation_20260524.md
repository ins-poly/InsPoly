# Event Forensic Weak-History Live/RPC Validation

This is a bounded measurement-only validation. It does not approve scorer tuning, runtime migration, Phase 3 capital-at-risk work, or gate changes.

## Gate Decision

- Gate: `weak_history_live_validation_needs_model_rfc`
- Output directory: `<repo>/validation_outputs/event_forensic_weak_history_live_rpc_20260524_112348`
- Network used: True
- Runtime behavior changed: False
- Saved artifacts mutated: False
- App storage mutated: False

## Bounds Used

- maxEvents: 3
- maxMarketsPerEvent: 8
- maxCandidateWalletsPerMarket: 150
- maxTotalTradeRows: 50000
- maxWallTimeSeconds: 1800

## Env/Config Status

- Secret values were not printed.
- Runtime env file present: True
- RPC configured: True
- CLOB/private auth configured but unused: False

## Targets

- Selected events: 1
- Selected markets: 1
- Selected target count: 1
- Excluded target count: 0

### weak_history_near_certainty_1

- Event: `russia-x-ukraine-ceasefire-by-january-31-2026`
- Market: Russia x Ukraine ceasefire by January 31, 2026?
- Input: https://polymarket.com/event/russia-x-ukraine-ceasefire-by-january-31-2026
- Source artifact: `event_forensic_outputs/event_forensic_20260503_183535/event_analysis.json`
- Reason: Existing saved Event Forensic artifact contains real weak-history near-certain later-winning rows.

## Row Counts

- Completed targets: 1
- Raw trade rows loaded: 3208
- Candidate rows: 144
- Weak-history rows: 4
- Near-certain economic rows: 14
- Weak-history near-certain later-win rows: 4
- High-rank weak-history near-certain later-win rows: 3

## Findings

- Fresh bounded output includes weak-history near-certain later-win rows in high review ranks. Reducers appear present, so this is a model-policy question rather than a narrow runtime bug.
- Phase 2 economic probability mismatches: 0
- Phase 4 cluster direction mismatches: 0

## Report Summaries

```json
[
  {
    "analysisNotes": [],
    "candidateTradeCount": 144,
    "displayTradeCount": 19,
    "eventAnalysisJsonPath": "<repo>/validation_outputs/event_forensic_weak_history_live_rpc_20260524_112348/live_runs/target_01/event_forensic_outputs/event_forensic_20260524_082352/event_analysis.json",
    "nearCertainEconomicRows": 14,
    "phase2EconomicProbabilityMismatches": 0,
    "phase4ClusterDirectionMismatches": 0,
    "rawTradeCount": 3208,
    "status": "completed",
    "suspiciousTradeCount": 19,
    "targetLabel": "weak_history_near_certainty_1",
    "weakHistoryNearCertainLaterWinCases": [
      {
        "clusterDirection": "long_no",
        "displayRank": 7,
        "economicSide": "NO",
        "economicSideProbability": "0.9589890085883432",
        "eventForensicScore": 6,
        "eventSlug": "russia-x-ukraine-ceasefire-by-january-31-2026",
        "existingModelClass": "Strong Risk",
        "laterWon": true,
        "market": "Russia x Ukraine ceasefire by January 31, 2026?",
        "nearCertainEconomicEntry": true,
        "nearCertaintyReducerPresent": true,
        "phase2EconomicProbabilityStatus": "match",
        "phase4ClusterDirectionStatus": "match",
        "rawOrderSide": "BUY",
        "rawTokenOutcome": "NO",
        "rawTokenPrice": "0.9589890085883432",
        "strongRiskGatePassed": "Yes",
        "summary": "The trade later won, but the wallet history is very weak and the entry was already near certainty.",
        "tradeKey": "0xd3d297a411f1f0dfbbfae1d6903ccdac109e8902a8ab5a600a7d0ef59628c523",
        "wallet": "0x6f3ebff1b1e46515c20782cc9b65581a7894ee32",
        "weakHistoryClassification": "weak_history",
        "weakHistoryNearCertainLaterWin": true,
        "weakHistoryReducerPresent": true,
        "winnerRank": 38
      },
      {
        "clusterDirection": "long_no",
        "displayRank": 8,
        "economicSide": "NO",
        "economicSideProbability": "0.958",
        "eventForensicScore": 6,
        "eventSlug": "russia-x-ukraine-ceasefire-by-january-31-2026",
        "existingModelClass": "Strong Risk",
        "laterWon": true,
        "market": "Russia x Ukraine ceasefire by January 31, 2026?",
        "nearCertainEconomicEntry": true,
        "nearCertaintyReducerPresent": true,
        "phase2EconomicProbabilityStatus": "match",
        "phase4ClusterDirectionStatus": "match",
        "rawOrderSide": "BUY",
        "rawTokenOutcome": "NO",
        "rawTokenPrice": "0.958",
        "strongRiskGatePassed": "Yes",
        "summary": "The trade later won, but the wallet history is very weak and the entry was already near certainty.",
        "tradeKey": "0x3458104679b410e74365e966f52de2d9085b0c50100daf12163927ba5750e761",
        "wallet": "0x80345f9d1b355a1477dd96e25465988191988488",
        "weakHistoryClassification": "weak_history",
        "weakHistoryNearCertainLaterWin": true,
        "weakHistoryReducerPresent": true,
        "winnerRank": 36
      },
      {
        "clusterDirection": "long_no",
        "displayRank": 9,
        "economicSide": "NO",
        "economicSideProbability": "0.9589090938015609",
        "eventForensicScore": 4,
        "eventSlug": "russia-x-ukraine-ceasefire-by-january-31-2026",
        "existingModelClass": "Strong Risk",
        "laterWon": true,
        "market": "Russia x Ukraine ceasefire by January 31, 2026?",
        "nearCertainEconomicEntry": true,
        "nearCertaintyReducerPresent": true,
        "phase2EconomicProbabilityStatus": "match",
        "phase4ClusterDirectionStatus": "match",
        "rawOrderSide": "BUY",
        "rawTokenOutcome": "NO",
        "rawTokenPrice": "0.9589090938015609",
        "strongRiskGatePassed": "Yes",
        "summary": "The trade later won, but the wallet history is very weak and the entry was already near certainty.",
        "tradeKey": "0xe339e81d4aa0d76351c7e3291798c28b8454071947b16d6d82e94522339d3eb8",
        "wallet": "0x4e1255034cb8827631bbcd0756c657962fdd7a56",
        "weakHistoryClassification": "weak_history",
        "weakHistoryNearCertainLaterWin": true,
        "weakHistoryReducerPresent": true,
        "winnerRank": 39
      },
      {
        "clusterDirection": "long_no",
        "displayRank": 16,
        "economicSide": "NO",
        "economicSideProbability": "0.996",
        "eventForensicScore": 0,
        "eventSlug": "russia-x-ukraine-ceasefire-by-january-31-2026",
        "existingModelClass": "Low Risk",
        "laterWon": true,
        "market": "Russia x Ukraine ceasefire by January 31, 2026?",
        "nearCertainEconomicEntry": true,
        "nearCertaintyReducerPresent": true,
        "phase2EconomicProbabilityStatus": "match",
        "phase4ClusterDirectionStatus": "match",
        "rawOrderSide": "BUY",
        "rawTokenOutcome": "NO",
        "rawTokenPrice": "0.996",
        "strongRiskGatePassed": "No",
        "summary": "The wallet has broad public prediction history and weak economics, so this is context unless concrete linkage evidence appears.",
        "tradeKey": "0xab70ef1e078758ad8719c42183942e0e098b0593b9d553a1791a7549c4752b74",
        "wallet": "0x709a4b4932cffc2d137fdb31c75d9a95842b7e39",
        "weakHistoryClassification": "weak_history",
        "weakHistoryNearCertainLaterWin": true,
        "weakHistoryReducerPresent": true,
        "winnerRank": 88
      }
    ],
    "weakHistoryRows": 4
  }
]
```

## Remaining Scope Blocks

- No scorer tuning was performed.
- Phase 3 capital-at-risk remains blocked.
- Strong Risk, HER, funding, candidate admission, storage, and UI sorting were not changed.
