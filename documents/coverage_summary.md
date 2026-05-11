# Alarm/Runbook Coverage Summary

- Coverage rows: **780**
- Match status counts: `{'matched_by_ref_path_normalized': 568, 'ref_path_missing': 115, 'heuristic_title_match': 9, 'no_runbook_ref': 88}`

## Top Alarm Families

| Family | Alarms | Status Breakdown |
| --- | ---: | --- |
| max_ambient | 71 | `{'matched_by_ref_path_normalized': 63, 'ref_path_missing': 3, 'no_runbook_ref': 5}` |
| cda_model | 51 | `{'matched_by_ref_path_normalized': 34, 'no_runbook_ref': 7, 'ref_path_missing': 10}` |
| sepsis_alert_service | 46 | `{'matched_by_ref_path_normalized': 46}` |
| cda_proposed_action_model | 37 | `{'matched_by_ref_path_normalized': 37}` |
| document_quality_improvement | 37 | `{'matched_by_ref_path_normalized': 37}` |
| cda_online_summaries | 36 | `{'matched_by_ref_path_normalized': 34, 'no_runbook_ref': 2}` |
| cda_proposed_action_model_qualitative | 30 | `{'ref_path_missing': 30}` |
| cda_subservice_canaries | 26 | `{'matched_by_ref_path_normalized': 24, 'ref_path_missing': 2}` |
| k8s | 22 | `{'matched_by_ref_path_normalized': 20, 'ref_path_missing': 2}` |
| services | 22 | `{'matched_by_ref_path_normalized': 22}` |
| atp | 21 | `{'matched_by_ref_path_normalized': 19, 'ref_path_missing': 2}` |
| watchdog | 21 | `{'ref_path_missing': 21}` |
| caa_oeo_patient_scheduling_agent | 16 | `{'heuristic_title_match': 6, 'no_runbook_ref': 10}` |
| cda_professional_fees | 16 | `{'matched_by_ref_path_normalized': 16}` |
| lightson | 16 | `{'matched_by_ref_path_normalized': 16}` |

## Top Missing Runbook Ref Paths

| Runbook Ref Path | Count |
| --- | ---: |
| pam/order_type_precision_regression | 10 |
| pam/order_type_recall_regression | 10 |
| pam/order_type_proposal_rate_regression | 10 |
| watchdog/sanity-failures | 9 |
| watchdog/pre-sanity-failures | 6 |
| watchdog/post-sanity-failures | 6 |
| controlplane/control-plane-deployments | 5 |
| tagging/tagging-failures | 5 |
| max-uec/websocket-sessions-exceed-limits | 4 |
| healthelife-db-api/heldb-index | 3 |
| note/kafaka_message_processing_pending | 2 |
| note/kafka_message_processing_pending | 2 |
| note/kafka_service_crashed | 2 |
| OHAIMAP/index | 2 |
| infrastructure/fss-mount-target-iops-throttling | 2 |
| ingress/max-slb-high-memory-usage | 2 |
| infrastructure/eks-unresponsive-host | 2 |
| max-ambient/event-processing-failure | 2 |
| max-proposed-actions/nanny-failure | 2 |
| atp/atp-logins | 1 |

## No-Ref Examples (sample)

- `caa_scheduling_agent_stuck_in_processing_shepherd_gating_alarm`
- `caa_scheduling_agent_low_traffic_high_upstream_5xx_error_alarm`
- `caa_scheduling_agent_low_traffic_high_upstream_4xx_error_alarm`
- `caa_scheduling_agent_low_traffic_high_timeout_error_alarm`
- `caa_scheduling_agent_low_traffic_high_llm_errors_alarm`
- `caa_scheduling_agent_low_traffic_high_llm_setup_errors_alarm`
- `caa_scheduling_agent_low_traffic_high_unclassified_errors_alarm`
- `caa_scheduling_agent_high_traffic_execution_error_rate_breach_alarm`
- `caa_scheduling_agent_high_traffic_execution_error_rate_breach_shepherd_gating_alarm`
- `caa_scheduling_agent_low_traffic_execution_error_rate_breach_shepherd_gating_alarm`
- `caad_api_responses_error_conditions`
- `caad_data_absence_alert`
- `data_action_ee_liveness`
- `data_action_ee_code_map_construction_exceptions`
- `data_action_ee_code_reconstruction_exceptions`
- `note_gen_4xx_llm_errors`
- `note_gen_5xx_llm_errors`
- `kafka_consumer_concurrent_tasks`
- `note_patient_metadata_download_failure`
- `note_debug_logs_emitted_for_model_prod`
