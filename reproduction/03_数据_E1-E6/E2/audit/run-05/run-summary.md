# E2 查询结果与金标准一致性 跑批报告

- case 数: 21 (pass 17)
- 缺金标准: 无
- 缺快照: 无
- metascore (反证夹具): 1.00 (必须 1.00)
- 判定: FAIL

| case | 加权分 | 阻断项 |
|------|--------|--------|
| batch_proximity | 0.9500 | m4_structure:structure_mismatch |
| boundary_maxrows | 1.0000 | — |
| boundary_page_exact | 1.0000 | — |
| boundary_pole_dec | 0.9986 | m3_units:dimension_probe_violation |
| boundary_radius0 | 1.0000 | — |
| boundary_wrap_ra | 1.0000 | — |
| cone_60as | 1.0000 | — |
| dense_field | 1.0000 | — |
| empty_field | 1.0000 | — |
| huge_batch_1000 | 0.5500 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| huge_over_cap | 0.3889 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| large_60000_rows | 1.0000 | — |
| missing_arg_catalog | 1.0000 | — |
| missing_arg_coords | 1.0000 | — |
| missing_arg_radius | 1.0000 | — |
| missing_cell | 1.0000 | — |
| missing_column | 1.0000 | — |
| multi_filter_mag_snr | 1.0000 | — |
| null_zero_twins | 1.0000 | — |
| single_exact | 1.0000 | — |
| soft404_page | 1.0000 | — |


- protocol: `E2-FROZEN-v2-2026-10-11`
- run_id: `e2-v2-9786b2e405364fab8737b749ed202469`
- repeats: 63/63
- complete: True
- elapsed: 28.94s
- preregistration SHA-256: `c671cf1229d10895779b167ac6354aa64c2c0ae58d9481ed83bce4fecdf4601e`
