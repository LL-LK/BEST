"""src.protocol_catalog_tables — 星表路由/列/波段/质量列的权威数据表 (纯数据, 无逻辑)。

能力边界: 只放 ``protocol`` 需要的星表侧大映射表 —— 查询路径表、导航分组、
旧拼写别名、显示名、``showcol`` 表单表、响应列清单、星等列映射、星等误差列映射、
质量列映射。**不含任何函数**, 也不发网络请求。
消费方: ``src/protocol.py`` (路由解析/表单拼装/列名映射/短表头修复)、
``src/models`` (波段归属)、``src/serialization`` (星等列单位判定)。

为什么单独成文: 这些表合计 571 净行纯数据 (实测; 本文件 730 物理行), 与协议逻辑混在一个文件里会把
"必须读的逻辑量"稀释掉 —— 400 行净代码预算约束的是逻辑量, 数据表不该占额度
(已在 docs/architecture/file-size-budget.md §3.11 登记: 超限全部是列名字符串
常量, 列清单的单一出处比文件行数更重要)。
``protocol.py`` 以 re-export 保留全部公开名字, 既有 import 路径不受影响。
"""
from __future__ import annotations  # 全表用 dict[...] 下标注解, 需此行在旧版解释器上不求值

# ==========================================================================
# 1. 查询路径表 (catalog -> /q 路由)
# ==========================================================================


# 星表查询路径表: 权威来源为线上服务实测 (逐个星表核对的可用路由), 消费方为
# resolve_catalog()/build_query_form() (拼 ``{BEST_BASE_URL}/{path}``) 与 src
# 客户端的查询入口; 键集同时是 catalog_from_path() 的反查依据。
#
# ``/q`` 路由只接受裸星表 id。``std`` / ``calib`` / ``other`` 只是 ``/f`` 表单页
# 上的导航分组, 不是可查询表 —— 带分组前缀的查询路径 (如 ``calib/stripe82/q``)
# 会返回 HTTP 200 + 响应体 ``{"error":"Not Found"}``, 即状态码门控看不见的软 404
# (见 is_soft_error / Soft404Error, P0-3)。
CATALOG_PATHS: dict[str, str] = {  # 值即 /q 路由; 键集同时是 catalog_from_path() 的反查依据
    "ps1": "ps1/q",  # 站点同时以 ``calib/ps1`` 发布, 同一张表 (table id 346)
    "stripe82": "stripe82/q",
    "gaia_dr3_18": "gaia_dr3_18/q",
    "jplus_dr3": "jplus_dr3/q",
    "smss_dr4": "smss_dr4/q",
    "landolt": "landolt/q",
    "uss_dr1": "uss_dr1/q",
    "splus_dr4": "splus_dr4/q",
    "scr_galah": "scr_galah/q",
    "scr_lamost": "scr_lamost/q",
    "xpsp": "xpsp/q",
    "dr3xpcorr": "dr3xpcorr/q",
}

# ==========================================================================
# 2. 导航分组 (不是可查询表)
# ==========================================================================


# 导航分组 -> 成员星表: 权威来源为 ``/f`` 表单页导航结构实测。消费方:
# resolve_catalog() (把分组名转成带成员列表的 ValueError, 拒绝误用) 与文档/展示层。
#
# ``std`` 是 Standard Stars 导航分组而非可查询表: ``/std/f`` 与 ``/std/q`` 都返回
# ``{"error":"Internal Server Error"}``, 所以分组名绝不能当表名查询。
CATALOG_GROUPS: dict[str, tuple[str, ...]] = {  # 导航分组不是可查询表: 组名当表名查会拿到内部错误
    "std": ("scr_galah", "scr_lamost", "xpsp"),  # Standard Stars 组: /std/f 与 /std/q 都返回内部错误
    "calib": (  # 定标星表组: 只有成员才有可用 /q 路由
        "ps1", "stripe82", "gaia_dr3_18", "jplus_dr3",
        "smss_dr4", "landolt", "uss_dr1", "splus_dr4",
    ),
    "other": ("dr3xpcorr",),  # 兜底分组: 发布的只有 dr3xpcorr 这一张改正光谱表
}

# ==========================================================================
# 3. 旧拼写别名归一
# ==========================================================================


# 旧拼写 -> 现存星表 id: 权威来源为历史调用方兼容需求 (包外仍有人传
# ``catalog="gaia_dr3"``)。消费方: resolve_catalog() / catalog_tables() /
# qualify_column() / models.BestSource.from_row (透传后查显式映射表)。
CATALOG_ALIASES: dict[str, str] = {"gaia_dr3": "gaia_dr3_18"}  # 唯一别名: 包外旧调用方仍传 catalog="gaia_dr3"

# ==========================================================================
# 4. 星表显示名
# ==========================================================================


# 星表 id -> 人类可读显示名: 权威来源为 BEST 站点星表页标题实测。消费方:
# models.CatalogType.display_name (单一出处, 模型层不再维护副本) 与 CLI/报告展示层;
# 表内缺失时 display_name 回退为星表 id 本身。
CATALOG_DISPLAY: dict[str, str] = {  # 星表 id -> 人类可读名; 表内缺失时 display_name 回退为 id 本身
    "ps1": "Pan-STARRS All-Sky",
    "stripe82": "Well-Calibrated Stripe82",
    "gaia_dr3_18": "Well-Calibrated Gaia DR3",
    "jplus_dr3": "Well-Calibrated J-PLUS DR3",
    "smss_dr4": "Well-Calibrated SMSS DR4",
    "landolt": "Well-Calibrated Landolt",
    "uss_dr1": "Well-Calibrated USS DR1",
    "splus_dr4": "Well-Calibrated S-PLUS DR4",
    "scr_galah": "Standard Stars (SCR GALAH)",
    "scr_lamost": "Standard Stars (SCR LAMOST)",
    "xpsp": "Standard Stars (Gaia DR3 XP&SP)",
    "dr3xpcorr": "Corrected Gaia DR3 XP Spectra",
}

# ==========================================================================
# 5. showcol 表单表 (列名 -> {table}.{col} 表单键)
# ==========================================================================


# 星表 -> 其 ``showcol`` 可取列的表名: 权威来源为星表表单页的表结构实测。消费方:
# catalog_tables() -> qualify_column() (列名 -> ``{table}.{col}`` 表单键) 与
# build_query_form()。
#
# 多数星表的列都在一张与星表同名的表单表下。XP 光谱星表例外, 跨多张表: 位置与
# Gaia 测光列在共享表, 改正光谱在各自表里, 所以那里的 ``showcol`` 键不是
# ``{catalog}.{col}``。
CATALOG_FORM_TABLES: dict[str, tuple[str, ...]] = {  # 该星表各列所在的表单表名; 多数与星表同名
    "gaia_dr3_18": ("gaia_dr3_18", "gaia_dr3"),  # 改正光谱在共享 gaia_dr3 表, 其余在同名表
    # xpsp 横跨 139 张表单表 (2026-09-29 线上核验):  Gaia 测光/位置在共享表
    # ``gaiaxp_photinfo_replenish``, 各调查的 XP 光谱拟合测光在各自的
    # ``{survey}_{band}`` 表 (``ps1_g.g_xpsp`` 形态)。仅登记共享表的话,
    # 276 个调查测光列会全部 fail-closed 拒绝 —— 故按线上全量登记。
    "xpsp": (  # 逐调查逐波段各一张表, 缺一列即拒绝, 因此这里必须列全
        "bass_g", "bass_r", "csst_g", "csst_i",
        "csst_r", "csst_u", "csst_y", "csst_z",
        "des_g", "des_i", "des_r", "des_y",
        "des_z", "gaiaxp_photinfo_replenish", "hipparcos_tycho_b", "hipparcos_tycho_hp",
        "hipparcos_tycho_v", "jkc_b", "jkc_i", "jkc_r",
        "jkc_u", "jkc_v", "jpas_gsdss", "jpas_isdss",
        "jpas_j0378", "jpas_j0390", "jpas_j0400", "jpas_j0410",
        "jpas_j0420", "jpas_j0430", "jpas_j0440", "jpas_j0450",
        "jpas_j0460", "jpas_j0470", "jpas_j0480", "jpas_j0490",
        "jpas_j0500", "jpas_j0510", "jpas_j0520", "jpas_j0530",
        "jpas_j0540", "jpas_j0550", "jpas_j0560", "jpas_j0570",
        "jpas_j0580", "jpas_j0590", "jpas_j0600", "jpas_j0610",
        "jpas_j0620", "jpas_j0630", "jpas_j0640", "jpas_j0650",
        "jpas_j0660", "jpas_j0670", "jpas_j0680", "jpas_j0690",
        "jpas_j0700", "jpas_j0710", "jpas_j0720", "jpas_j0730",
        "jpas_j0740", "jpas_j0750", "jpas_j0760", "jpas_j0770",
        "jpas_j0780", "jpas_j0790", "jpas_j0800", "jpas_j0810",
        "jpas_j0820", "jpas_j0830", "jpas_j0840", "jpas_j0850",
        "jpas_j0860", "jpas_j0870", "jpas_j0880", "jpas_j0890",
        "jpas_j0900", "jpas_j0910", "jpas_j1007", "jpas_rsdss",
        "jpas_u", "jpas_ujava", "jplus_gsdss", "jplus_isdss",
        "jplus_j0378", "jplus_j0395", "jplus_j0410", "jplus_j0430",
        "jplus_j0515", "jplus_j0660", "jplus_j0861", "jplus_rsdss",
        "jplus_ujava", "jplus_zsdss", "kepler_k", "lsst_g",
        "lsst_i", "lsst_r", "lsst_u", "lsst_y",
        "lsst_z", "mephisto_g", "mephisto_i", "mephisto_r",
        "mephisto_u", "mephisto_v", "mephisto_z", "ps1_g",
        "ps1_i", "ps1_r", "ps1_y", "ps1_z",
        "sdss_g", "sdss_i", "sdss_r", "sdss_u",
        "sdss_z", "skymapper_g", "skymapper_i", "skymapper_r",
        "skymapper_u", "skymapper_v", "skymapper_z", "splus_f378",
        "splus_f395", "splus_f410", "splus_f430", "splus_f515",
        "splus_f660", "splus_f861", "splus_g", "splus_i",
        "splus_r", "splus_u", "splus_z", "tess_red",
        "ztf_g", "ztf_i", "ztf_r",
    ),
    "dr3xpcorr": ("gaiaxp_photinfo_replenish", "correctedxpspecv1"),  # 测光在共享表, 改正谱在专表
}

# ==========================================================================
# 6. 响应列清单
# ==========================================================================


# 星表 -> BEST CSV 端点在该星表提交对应 ``showcol`` 后返回的响应字段名。权威来源:
# 各星表表单页逐个核对 (而非从示例行反推), 锚点 contracts/fields/*.contract.yaml。
# 消费方: build_query_form() 的默认 showcol (未显式指定列时请求整表列)、
# parse_csv_rows() 的旧式短表头修复路径, 以及模型层/文档层。
CATALOG_COLUMNS: dict[str, list[str]] = {  # 列名字面量的单一出处, 改列名只改这一处
    "ps1": [  # 30 列 (AST 实测): 5 个 PSF 星等 + 误差 + class_star/EBV/视差等
        "ps1_ra", "ps1_dec", "ps1_class_star", "ps1_dust", "ps1_ebv",
        "ps1_gflags", "ps1_gpsf", "ps1_gpsf_corr", "ps1_gpsf_err",
        "ps1_iflags", "ps1_ipsf", "ps1_ipsf_corr", "ps1_ipsf_err",
        "ps1_max_d", "ps1_parallax", "ps1_parallax_err", "ps1_rflags",
        "ps1_rpsf", "ps1_rpsf_corr", "ps1_rpsf_err", "ps1_ruwe",
        "ps1_sigma", "ps1_source_id", "ps1_yflags", "ps1_ypsf",
        "ps1_ypsf_err", "ps1_zflags", "ps1_zpsf", "ps1_zpsf_corr",
        "ps1_zpsf_err",
    ],
    "stripe82": [  # 42 列 (AST 实测): **u**/g/r/i/z 五列 H22 改正星等 (含 u_h22) + 各波段 RMS/χ² 质量块
        "stripe82_calibstars_id", "stripe82_ra", "stripe82_dec",
        "stripe82_rarms", "stripe82_decrms", "stripe82_nb", "stripe82_ar",
        "stripe82_unobs", "stripe82_ummed", "stripe82_ummu",
        "stripe82_umsig", "stripe82_umrms", "stripe82_umchi2",
        "stripe82_gnobs", "stripe82_gmmed", "stripe82_gmmu",
        "stripe82_gmsig", "stripe82_gmrms", "stripe82_gmchi2",
        "stripe82_rnobs", "stripe82_rmmed", "stripe82_rmmu",
        "stripe82_rmsig", "stripe82_rmrms", "stripe82_rmchi2",
        "stripe82_inobs", "stripe82_immed", "stripe82_immu",
        "stripe82_imsig", "stripe82_imrms", "stripe82_imchi2",
        "stripe82_znobs", "stripe82_zmmed", "stripe82_zmmu",
        "stripe82_zmsig", "stripe82_zmrms", "stripe82_zmchi2",
        "stripe82_u_h22", "stripe82_g_h22", "stripe82_r_h22",
        "stripe82_i_h22", "stripe82_z_h22",
    ],
    # 2026-09-29 线上核验: 站点发布 155 列 (完整 Gaia DR3 星表字段);
    # 流量/相关性修正/RV 参数/天体测量细节等 128 列同样可请求, 一并登记。
    "gaia_dr3_18": [  # 155 列: 天体测量 + 测光 + RV + BP/RV 分光星等
        "gaia_dr3_18_solution_id", "gaia_dr3_18_designation", "gaia_dr3_18_source_id",
        "gaia_dr3_18_random_index", "gaia_dr3_18_ref_epoch", "gaia_dr3_18_ra",
        "gaia_dr3_18_ra_error", "gaia_dr3_18_dec", "gaia_dr3_18_dec_error",
        "gaia_dr3_18_parallax", "gaia_dr3_18_parallax_error",
        "gaia_dr3_18_parallax_over_error", "gaia_dr3_18_pm", "gaia_dr3_18_pmra",
        "gaia_dr3_18_pmra_error", "gaia_dr3_18_pmdec", "gaia_dr3_18_pmdec_error",
        "gaia_dr3_18_ra_dec_corr", "gaia_dr3_18_ra_parallax_corr",
        "gaia_dr3_18_ra_pmra_corr", "gaia_dr3_18_ra_pmdec_corr",
        "gaia_dr3_18_dec_parallax_corr", "gaia_dr3_18_dec_pmra_corr",
        "gaia_dr3_18_dec_pmdec_corr", "gaia_dr3_18_parallax_pmra_corr",
        "gaia_dr3_18_parallax_pmdec_corr", "gaia_dr3_18_pmra_pmdec_corr",
        "gaia_dr3_18_astrometric_n_obs_al", "gaia_dr3_18_astrometric_n_obs_ac",
        "gaia_dr3_18_astrometric_n_good_obs_al",
        "gaia_dr3_18_astrometric_n_bad_obs_al", "gaia_dr3_18_astrometric_gof_al",
        "gaia_dr3_18_astrometric_chi2_al", "gaia_dr3_18_astrometric_excess_noise",
        "gaia_dr3_18_astrometric_excess_noise_sig",
        "gaia_dr3_18_astrometric_params_solved",
        "gaia_dr3_18_astrometric_primary_flag",
        "gaia_dr3_18_nu_eff_used_in_astrometry", "gaia_dr3_18_pseudocolour",
        "gaia_dr3_18_pseudocolour_error", "gaia_dr3_18_ra_pseudocolour_corr",
        "gaia_dr3_18_dec_pseudocolour_corr", "gaia_dr3_18_parallax_pseudocolour_corr",
        "gaia_dr3_18_pmra_pseudocolour_corr", "gaia_dr3_18_pmdec_pseudocolour_corr",
        "gaia_dr3_18_astrometric_matched_transits",
        "gaia_dr3_18_visibility_periods_used", "gaia_dr3_18_astrometric_sigma5d_max",
        "gaia_dr3_18_matched_transits", "gaia_dr3_18_new_matched_transits",
        "gaia_dr3_18_matched_transits_removed",
        "gaia_dr3_18_ipd_gof_harmonic_amplitude", "gaia_dr3_18_ipd_gof_harmonic_phase",
        "gaia_dr3_18_ipd_frac_multi_peak", "gaia_dr3_18_ipd_frac_odd_win",
        "gaia_dr3_18_ruwe", "gaia_dr3_18_scan_direction_strength_k1",
        "gaia_dr3_18_scan_direction_strength_k2",
        "gaia_dr3_18_scan_direction_strength_k3",
        "gaia_dr3_18_scan_direction_strength_k4", "gaia_dr3_18_scan_direction_mean_k1",
        "gaia_dr3_18_scan_direction_mean_k2", "gaia_dr3_18_scan_direction_mean_k3",
        "gaia_dr3_18_scan_direction_mean_k4", "gaia_dr3_18_duplicated_source",
        "gaia_dr3_18_phot_g_n_obs", "gaia_dr3_18_phot_g_mean_flux",
        "gaia_dr3_18_phot_g_mean_flux_error",
        "gaia_dr3_18_phot_g_mean_flux_over_error", "gaia_dr3_18_phot_g_mean_mag",
        "gaia_dr3_18_phot_bp_n_obs", "gaia_dr3_18_phot_bp_mean_flux",
        "gaia_dr3_18_phot_bp_mean_flux_error",
        "gaia_dr3_18_phot_bp_mean_flux_over_error", "gaia_dr3_18_phot_bp_mean_mag",
        "gaia_dr3_18_phot_rp_n_obs", "gaia_dr3_18_phot_rp_mean_flux",
        "gaia_dr3_18_phot_rp_mean_flux_error",
        "gaia_dr3_18_phot_rp_mean_flux_over_error", "gaia_dr3_18_phot_rp_mean_mag",
        "gaia_dr3_18_phot_bp_rp_excess_factor",
        "gaia_dr3_18_phot_bp_n_contaminated_transits",
        "gaia_dr3_18_phot_bp_n_blended_transits",
        "gaia_dr3_18_phot_rp_n_contaminated_transits",
        "gaia_dr3_18_phot_rp_n_blended_transits", "gaia_dr3_18_phot_proc_mode",
        "gaia_dr3_18_bp_rp", "gaia_dr3_18_bp_g", "gaia_dr3_18_g_rp",
        "gaia_dr3_18_radial_velocity", "gaia_dr3_18_radial_velocity_error",
        "gaia_dr3_18_rv_method_used", "gaia_dr3_18_rv_nb_transits",
        "gaia_dr3_18_rv_nb_deblended_transits",
        "gaia_dr3_18_rv_visibility_periods_used",
        "gaia_dr3_18_rv_expected_sig_to_noise", "gaia_dr3_18_rv_renormalised_gof",
        "gaia_dr3_18_rv_chisq_pvalue", "gaia_dr3_18_rv_time_duration",
        "gaia_dr3_18_rv_amplitude_robust", "gaia_dr3_18_rv_template_teff",
        "gaia_dr3_18_rv_template_logg", "gaia_dr3_18_rv_template_fe_h",
        "gaia_dr3_18_rv_atm_param_origin", "gaia_dr3_18_vbroad",
        "gaia_dr3_18_vbroad_error", "gaia_dr3_18_vbroad_nb_transits",
        "gaia_dr3_18_grvs_mag", "gaia_dr3_18_grvs_mag_error",
        "gaia_dr3_18_grvs_mag_nb_transits", "gaia_dr3_18_rvs_spec_sig_to_noise",
        "gaia_dr3_18_phot_variable_flag", "gaia_dr3_18_l", "gaia_dr3_18_b",
        "gaia_dr3_18_ecl_lon", "gaia_dr3_18_ecl_lat", "gaia_dr3_18_in_qso_candidates",
        "gaia_dr3_18_in_galaxy_candidates", "gaia_dr3_18_non_single_star",
        "gaia_dr3_18_has_xp_continuous", "gaia_dr3_18_has_xp_sampled",
        "gaia_dr3_18_has_rvs", "gaia_dr3_18_has_epoch_photometry",
        "gaia_dr3_18_has_epoch_rv", "gaia_dr3_18_has_mcmc_gspphot",
        "gaia_dr3_18_has_mcmc_msc", "gaia_dr3_18_in_andromeda_survey",
        "gaia_dr3_18_classprob_dsc_combmod_quasar",
        "gaia_dr3_18_classprob_dsc_combmod_galaxy",
        "gaia_dr3_18_classprob_dsc_combmod_star", "gaia_dr3_18_teff_gspphot",
        "gaia_dr3_18_teff_gspphot_lower", "gaia_dr3_18_teff_gspphot_upper",
        "gaia_dr3_18_logg_gspphot", "gaia_dr3_18_logg_gspphot_lower",
        "gaia_dr3_18_logg_gspphot_upper", "gaia_dr3_18_mh_gspphot",
        "gaia_dr3_18_mh_gspphot_lower", "gaia_dr3_18_mh_gspphot_upper",
        "gaia_dr3_18_distance_gspphot", "gaia_dr3_18_distance_gspphot_lower",
        "gaia_dr3_18_distance_gspphot_upper", "gaia_dr3_18_azero_gspphot",
        "gaia_dr3_18_azero_gspphot_lower", "gaia_dr3_18_azero_gspphot_upper",
        "gaia_dr3_18_ag_gspphot", "gaia_dr3_18_ag_gspphot_lower",
        "gaia_dr3_18_ag_gspphot_upper", "gaia_dr3_18_ebpminrp_gspphot",
        "gaia_dr3_18_ebpminrp_gspphot_lower", "gaia_dr3_18_ebpminrp_gspphot_upper",
        "gaia_dr3_18_libname_gspphot", "gaia_dr3_18_phot_g_mean_mag_y21",
        "gaia_dr3_18_phot_bp_mean_mag_y21", "gaia_dr3_18_phot_rp_mean_mag_y21",
    ],
    # 旧拼写 ``gaia_dr3`` 不得再在此处留一份 155 项的列清单副本: 它与上方
    # ``gaia_dr3_18`` 逐项全等, 两份漂移起来无从发现。兼容一律由
    # ``CATALOG_ALIASES`` + 各调用点的别名归一承担 (protocol 层本就先归一;
    # tap/adql、tap/service、tap/jobs、models 四处均已归一), 单一出处比留
    # 一份副本更重要。
    "jplus_dr3": [  # 8 列: 唯一直径测光 mag_aper_6_0_final
        "jplus_dr3_ra", "jplus_dr3_dec", "jplus_dr3_aper_corr",
        "jplus_dr3_aper_corr_err", "jplus_dr3_zp1", "jplus_dr3_zp2",
        "jplus_dr3_cflag", "jplus_dr3_mag_aper_6_0_final",
    ],
    # 2026-09-29 线上核验: 站点已重构 smss_dr4 —— ``source_id`` 与
    # ``psf_mag`` 不再发布 (幻影列: 服务端静默丢弃未知 showcol 键), 现行为
    # 6 个波段 PSF 星等列。证据 temp/audit_column_drift_results.json。
    "smss_dr4": [  # 8 列: ra/dec + 6 个波段 PSF 星等 (source_id/psf_mag 站点已不发布)
        "smss_dr4_ra", "smss_dr4_dec", "smss_dr4_upsf", "smss_dr4_vpsf",
        "smss_dr4_gpsf", "smss_dr4_rpsf", "smss_dr4_ipsf", "smss_dr4_zpsf",
    ],
    "landolt": [  # 49 列 (AST 实测): 视宁度 d_umag 系列 + Gaia 测光 + 改正星等
        "landolt_field", "landolt_star", "landolt_raj2000",
        "landolt_dej2000", "landolt_umag", "landolt_e_umag",
        "landolt_o_umag", "landolt_bmag", "landolt_e_bmag",
        "landolt_o_bmag", "landolt_vmag", "landolt_e_vmag",
        "landolt_o_vmag", "landolt_rmag", "landolt_e_rmag",
        "landolt_o_rmag", "landolt_imag", "landolt_e_imag",
        "landolt_o_imag", "landolt_u_b", "landolt_e_u_b", "landolt_b_v",
        "landolt_e_b_v", "landolt_v_r", "landolt_e_v_r", "landolt_r_i",
        "landolt_e_r_i", "landolt_v_i", "landolt_e_v_i",
        "landolt_source_id", "landolt_ra", "landolt_dec",
        "landolt_parallax", "landolt_pmra", "landolt_pmdec",
        "landolt_bp_mag", "landolt_rp_mag", "landolt_g_mag",
        "landolt_ruwe", "landolt_excess_factor", "landolt_u_corrected",
        "landolt_b_corrected", "landolt_v_corrected", "landolt_r_corrected",
        "landolt_i_corrected", "landolt_is_calibrator", "landolt_from",
        "landolt_cali_set", "landolt_ff_set",
    ],
    # 2026-09-29 线上核验: 站点已把 uss_dr1 重构为**按波段测量** ——
    # ``source_id``/``ra``/``dec``/``psf_mag`` 全部不再发布 (幻影列), 改为 12 个
    # 波段 (u/g/r/i/z + JPAS/J-PLUS 窄带) 各自的位置/测光/flag/class_star。
    # 注意: 该星表 CSV 响应列名是**裸名** (``ra_u``/``u_pstotal``, 站点
    # datagrid 才用 ``uss_dr1_`` 前缀), 因此没有规范化 ra/dec —— 星等列以
    # 裸名直接命中 CATALOG_MAG_COLUMNS (见该表 uss_dr1 条目注释)。
    "uss_dr1": [  # 12 波段各自的位置/星等/误差/flag/class_star, 共 96 列 (AST 实测)
        "uss_dr1_ra_u", "uss_dr1_dec_u", "uss_dr1_u_pstotal", "uss_dr1_ra_j0378",
        "uss_dr1_dec_j0378", "uss_dr1_j0378_pstotal", "uss_dr1_ra_j0395",
        "uss_dr1_dec_j0395", "uss_dr1_j0395_pstotal", "uss_dr1_ra_j0410",
        "uss_dr1_dec_j0410", "uss_dr1_j0410_pstotal", "uss_dr1_ra_j0430",
        "uss_dr1_dec_j0430", "uss_dr1_j0430_pstotal", "uss_dr1_ra_g", "uss_dr1_dec_g",
        "uss_dr1_g_pstotal", "uss_dr1_ra_j0515", "uss_dr1_dec_j0515",
        "uss_dr1_j0515_pstotal", "uss_dr1_ra_r", "uss_dr1_dec_r", "uss_dr1_r_pstotal",
        "uss_dr1_ra_j0660", "uss_dr1_dec_j0660", "uss_dr1_j0660_pstotal",
        "uss_dr1_ra_i", "uss_dr1_dec_i", "uss_dr1_i_pstotal", "uss_dr1_ra_j0861",
        "uss_dr1_dec_j0861", "uss_dr1_j0861_pstotal", "uss_dr1_ra_z", "uss_dr1_dec_z",
        "uss_dr1_z_pstotal", "uss_dr1_u_pstotal_corr_final", "uss_dr1_u_pstotal_d202",
        "uss_dr1_j0378_pstotal_corr_final", "uss_dr1_j0378_pstotal_d202",
        "uss_dr1_j0395_pstotal_corr_final", "uss_dr1_j0395_pstotal_d202",
        "uss_dr1_j0410_pstotal_corr_final", "uss_dr1_j0410_pstotal_d202",
        "uss_dr1_j0430_pstotal_corr_final", "uss_dr1_j0430_pstotal_d202",
        "uss_dr1_g_pstotal_corr_final", "uss_dr1_g_pstotal_d202",
        "uss_dr1_j0515_pstotal_corr_final", "uss_dr1_j0515_pstotal_d202",
        "uss_dr1_r_pstotal_corr_final", "uss_dr1_r_pstotal_d202",
        "uss_dr1_j0660_pstotal_corr_final", "uss_dr1_j0660_pstotal_d202",
        "uss_dr1_i_pstotal_corr_final", "uss_dr1_i_pstotal_d202",
        "uss_dr1_j0861_pstotal_corr_final", "uss_dr1_j0861_pstotal_d202",
        "uss_dr1_z_pstotal_corr_final", "uss_dr1_z_pstotal_d202", "uss_dr1_u_flag",
        "uss_dr1_u_class_star", "uss_dr1_u_err_pstotal", "uss_dr1_j0378_flag",
        "uss_dr1_j0378_class_star", "uss_dr1_j0378_err_pstotal", "uss_dr1_j0395_flag",
        "uss_dr1_j0395_class_star", "uss_dr1_j0395_err_pstotal", "uss_dr1_j0410_flag",
        "uss_dr1_j0410_class_star", "uss_dr1_j0410_err_pstotal", "uss_dr1_j0430_flag",
        "uss_dr1_j0430_class_star", "uss_dr1_j0430_err_pstotal", "uss_dr1_g_flag",
        "uss_dr1_g_class_star", "uss_dr1_g_err_pstotal", "uss_dr1_j0515_flag",
        "uss_dr1_j0515_class_star", "uss_dr1_j0515_err_pstotal", "uss_dr1_r_flag",
        "uss_dr1_r_class_star", "uss_dr1_r_err_pstotal", "uss_dr1_j0660_flag",
        "uss_dr1_j0660_class_star", "uss_dr1_j0660_err_pstotal", "uss_dr1_i_flag",
        "uss_dr1_i_class_star", "uss_dr1_i_err_pstotal", "uss_dr1_j0861_flag",
        "uss_dr1_j0861_class_star", "uss_dr1_j0861_err_pstotal", "uss_dr1_z_flag",
        "uss_dr1_z_class_star", "uss_dr1_z_err_pstotal",
    ],
    "splus_dr4": [  # 12 波段 pstotal + 同名 e_* 误差 + 5 个 s2n/corr 列
        "splus_dr4_id", "splus_dr4_ra", "splus_dr4_dec",
        "splus_dr4_u_pstotal", "splus_dr4_j0378_pstotal",
        "splus_dr4_j0395_pstotal", "splus_dr4_j0410_pstotal",
        "splus_dr4_j0430_pstotal", "splus_dr4_g_pstotal",
        "splus_dr4_j0515_pstotal", "splus_dr4_r_pstotal",
        "splus_dr4_j0660_pstotal", "splus_dr4_i_pstotal",
        "splus_dr4_j0861_pstotal", "splus_dr4_z_pstotal",
        "splus_dr4_e_u_pstotal", "splus_dr4_e_j0378_pstotal",
        "splus_dr4_e_j0395_pstotal", "splus_dr4_e_j0410_pstotal",
        "splus_dr4_e_j0430_pstotal", "splus_dr4_e_g_pstotal",
        "splus_dr4_e_j0515_pstotal", "splus_dr4_e_r_pstotal",
        "splus_dr4_e_j0660_pstotal", "splus_dr4_e_i_pstotal",
        "splus_dr4_e_j0861_pstotal", "splus_dr4_e_z_pstotal",
        "splus_dr4_s2n_det_auto", "splus_dr4_sex_flags_det",
        "splus_dr4_r_corr", "splus_dr4_g_corr", "splus_dr4_i_corr",
        "splus_dr4_z_corr", "splus_dr4_u_corr", "splus_dr4_j0378_corr",
        "splus_dr4_j0395_corr", "splus_dr4_j0410_corr",
        "splus_dr4_j0430_corr", "splus_dr4_j0515_corr",
        "splus_dr4_j0660_corr", "splus_dr4_j0861_corr",
    ],
    # 2026-09-29 线上核验: 站点发布 137 列 —— JPAS/J-PLUS
    # 窄带、LSST/CSST/Mephisto/BASS/SMSS/ZTF 交叉匹配测光等 104 列一并登记。
    # 未收录 CATALOG_MAG_COLUMNS 的交叉列只进 raw_data; 收录列若有多调查同波段,
    # from_row 赋值由首个有值的列胜出决定 (禁止后出现列覆盖, 见 src/models/__init__.py:420)。
    "scr_galah": [  # 137 列: 原生 SCR 测光 + 多调查交叉匹配列 (只进 raw_data)
        "scr_galah_ra", "scr_galah_dec", "scr_galah_j0780jpas", "scr_galah_j0790jpas",
        "scr_galah_j0800jpas", "scr_galah_j0810jpas", "scr_galah_j0820jpas",
        "scr_galah_j0830jpas", "scr_galah_j0840jpas", "scr_galah_j0850jpas",
        "scr_galah_j0860jpas", "scr_galah_j0870jpas", "scr_galah_j0880jpas",
        "scr_galah_j0890jpas", "scr_galah_j0900jpas", "scr_galah_j0910jpas",
        "scr_galah_j1007jpas", "scr_galah_gsdssjpas", "scr_galah_isdssjpas",
        "scr_galah_rsdssjpas", "scr_galah_ujpas", "scr_galah_ujavajpas",
        "scr_galah_j0580jpas", "scr_galah_j0590jpas", "scr_galah_j0600jpas",
        "scr_galah_j0610jpas", "scr_galah_j0620jpas", "scr_galah_j0630jpas",
        "scr_galah_j0640jpas", "scr_galah_j0650jpas", "scr_galah_j0660jpas",
        "scr_galah_j0670jpas", "scr_galah_j0680jpas", "scr_galah_j0690jpas",
        "scr_galah_j0700jpas", "scr_galah_j0710jpas", "scr_galah_j0720jpas",
        "scr_galah_j0730jpas", "scr_galah_j0740jpas", "scr_galah_j0750jpas",
        "scr_galah_j0760jpas", "scr_galah_j0770jpas", "scr_galah_j0378jpas",
        "scr_galah_j0390jpas", "scr_galah_j0400jpas", "scr_galah_j0410jpas",
        "scr_galah_j0420jpas", "scr_galah_j0430jpas", "scr_galah_j0440jpas",
        "scr_galah_j0450jpas", "scr_galah_j0460jpas", "scr_galah_j0470jpas",
        "scr_galah_j0480jpas", "scr_galah_j0490jpas", "scr_galah_j0500jpas",
        "scr_galah_j0510jpas", "scr_galah_j0520jpas", "scr_galah_j0530jpas",
        "scr_galah_j0540jpas", "scr_galah_j0550jpas", "scr_galah_j0560jpas",
        "scr_galah_j0570jpas", "scr_galah_bapass", "scr_galah_vapass",
        "scr_galah_gapass", "scr_galah_iapass", "scr_galah_rapass", "scr_galah_zapass",
        "scr_galah_gbass", "scr_galah_rbass", "scr_galah_gcsst", "scr_galah_icsst",
        "scr_galah_rcsst", "scr_galah_ucsst", "scr_galah_ycsst", "scr_galah_zcsst",
        "scr_galah_ujkc", "scr_galah_bjkc", "scr_galah_vjkc", "scr_galah_rjkc",
        "scr_galah_ijkc", "scr_galah_j0378jplus", "scr_galah_j0395jplus",
        "scr_galah_j0410jplus", "scr_galah_j0430jplus", "scr_galah_j0515jplus",
        "scr_galah_j0660jplus", "scr_galah_j0861jplus", "scr_galah_gjplus",
        "scr_galah_ijplus", "scr_galah_rjplus", "scr_galah_ujplus", "scr_galah_zjplus",
        "scr_galah_glsst", "scr_galah_ilsst", "scr_galah_rlsst", "scr_galah_ulsst",
        "scr_galah_ylsst", "scr_galah_zlsst", "scr_galah_gmephisto",
        "scr_galah_imephisto", "scr_galah_rmephisto", "scr_galah_umephisto",
        "scr_galah_vmephisto", "scr_galah_zmephisto", "scr_galah_gps1",
        "scr_galah_ips1", "scr_galah_rps1", "scr_galah_yps1", "scr_galah_zps1",
        "scr_galah_gsdss", "scr_galah_isdss", "scr_galah_rsdss", "scr_galah_usdss",
        "scr_galah_zsdss", "scr_galah_gsmss", "scr_galah_ismss", "scr_galah_rsmss",
        "scr_galah_usmss", "scr_galah_vsmss", "scr_galah_zsmss", "scr_galah_f378splus",
        "scr_galah_f395splus", "scr_galah_f410splus", "scr_galah_f430splus",
        "scr_galah_f515splus", "scr_galah_f660splus", "scr_galah_f861splus",
        "scr_galah_gsplus", "scr_galah_isplus", "scr_galah_rsplus", "scr_galah_usplus",
        "scr_galah_zsplus", "scr_galah_gztf", "scr_galah_iztf", "scr_galah_rztf",
        "scr_galah_source_id",
    ],
    # 2026-09-29 线上核验: 站点发布 137 列 —— JPAS/J-PLUS
    # 窄带、LSST/CSST/Mephisto/BASS/SMSS/ZTF 交叉匹配测光等 104 列一并登记。
    # 未收录 CATALOG_MAG_COLUMNS 的交叉列只进 raw_data; 收录列若有多调查同波段,
    # from_row 赋值由 CSV 列遍历顺序决定 (后出现列覆盖, 见 CATALOG_MAG_COLUMNS)。
    "scr_lamost": [  # 137 列: 与 scr_galah 同构, 交叉测光同样只进 raw_data
        "scr_lamost_ra", "scr_lamost_dec", "scr_lamost_j0780jpas",
        "scr_lamost_j0790jpas", "scr_lamost_j0800jpas", "scr_lamost_j0810jpas",
        "scr_lamost_j0820jpas", "scr_lamost_j0830jpas", "scr_lamost_j0840jpas",
        "scr_lamost_j0850jpas", "scr_lamost_j0860jpas", "scr_lamost_j0870jpas",
        "scr_lamost_j0880jpas", "scr_lamost_j0890jpas", "scr_lamost_j0900jpas",
        "scr_lamost_j0910jpas", "scr_lamost_j1007jpas", "scr_lamost_gsdssjpas",
        "scr_lamost_isdssjpas", "scr_lamost_rsdssjpas", "scr_lamost_ujpas",
        "scr_lamost_ujavajpas", "scr_lamost_j0580jpas", "scr_lamost_j0590jpas",
        "scr_lamost_j0600jpas", "scr_lamost_j0610jpas", "scr_lamost_j0620jpas",
        "scr_lamost_j0630jpas", "scr_lamost_j0640jpas", "scr_lamost_j0650jpas",
        "scr_lamost_j0660jpas", "scr_lamost_j0670jpas", "scr_lamost_j0680jpas",
        "scr_lamost_j0690jpas", "scr_lamost_j0700jpas", "scr_lamost_j0710jpas",
        "scr_lamost_j0720jpas", "scr_lamost_j0730jpas", "scr_lamost_j0740jpas",
        "scr_lamost_j0750jpas", "scr_lamost_j0760jpas", "scr_lamost_j0770jpas",
        "scr_lamost_j0378jpas", "scr_lamost_j0390jpas", "scr_lamost_j0400jpas",
        "scr_lamost_j0410jpas", "scr_lamost_j0420jpas", "scr_lamost_j0430jpas",
        "scr_lamost_j0440jpas", "scr_lamost_j0450jpas", "scr_lamost_j0460jpas",
        "scr_lamost_j0470jpas", "scr_lamost_j0480jpas", "scr_lamost_j0490jpas",
        "scr_lamost_j0500jpas", "scr_lamost_j0510jpas", "scr_lamost_j0520jpas",
        "scr_lamost_j0530jpas", "scr_lamost_j0540jpas", "scr_lamost_j0550jpas",
        "scr_lamost_j0560jpas", "scr_lamost_j0570jpas", "scr_lamost_bapass",
        "scr_lamost_vapass", "scr_lamost_gapass", "scr_lamost_iapass",
        "scr_lamost_rapass", "scr_lamost_zapass", "scr_lamost_gbass",
        "scr_lamost_rbass", "scr_lamost_gcsst", "scr_lamost_icsst", "scr_lamost_rcsst",
        "scr_lamost_ucsst", "scr_lamost_ycsst", "scr_lamost_zcsst", "scr_lamost_ujkc",
        "scr_lamost_bjkc", "scr_lamost_vjkc", "scr_lamost_rjkc", "scr_lamost_ijkc",
        "scr_lamost_j0378jplus", "scr_lamost_j0395jplus", "scr_lamost_j0410jplus",
        "scr_lamost_j0430jplus", "scr_lamost_j0515jplus", "scr_lamost_j0660jplus",
        "scr_lamost_j0861jplus", "scr_lamost_gjplus", "scr_lamost_ijplus",
        "scr_lamost_rjplus", "scr_lamost_ujplus", "scr_lamost_zjplus",
        "scr_lamost_glsst", "scr_lamost_ilsst", "scr_lamost_rlsst", "scr_lamost_ulsst",
        "scr_lamost_ylsst", "scr_lamost_zlsst", "scr_lamost_gmephisto",
        "scr_lamost_imephisto", "scr_lamost_rmephisto", "scr_lamost_umephisto",
        "scr_lamost_vmephisto", "scr_lamost_zmephisto", "scr_lamost_gps1",
        "scr_lamost_ips1", "scr_lamost_rps1", "scr_lamost_yps1", "scr_lamost_zps1",
        "scr_lamost_gsdss", "scr_lamost_isdss", "scr_lamost_rsdss", "scr_lamost_usdss",
        "scr_lamost_zsdss", "scr_lamost_gsmss", "scr_lamost_ismss", "scr_lamost_rsmss",
        "scr_lamost_usmss", "scr_lamost_vsmss", "scr_lamost_zsmss",
        "scr_lamost_f378splus", "scr_lamost_f395splus", "scr_lamost_f410splus",
        "scr_lamost_f430splus", "scr_lamost_f515splus", "scr_lamost_f660splus",
        "scr_lamost_f861splus", "scr_lamost_gsplus", "scr_lamost_isplus",
        "scr_lamost_rsplus", "scr_lamost_usplus", "scr_lamost_zsplus",
        "scr_lamost_gztf", "scr_lamost_iztf", "scr_lamost_rztf",
        "scr_lamost_source_id",
    ],
    # 2026-09-29 线上核验: 287 个可选列横跨 139 张表单表 (共享表 11 列)。响应列名 = ``{table}_{col}`` (如 ``ps1_g.g_xpsp`` ->
    # ``ps1_g_g_xpsp``)。调查测光列只进 raw_data, magnitudes 保持 Gaia
    # G/BP/RP 三列 (见 CATALOG_MAG_COLUMNS.xpsp)。
    "xpsp": [  # 287 列: 共享表 11 列 + 139 张调查表逐列拼成
        "gaiaxp_photinfo_replenish_source_id", "gaiaxp_photinfo_replenish_ra",
        "gaiaxp_photinfo_replenish_dec", "gaiaxp_photinfo_replenish_parallax",
        "gaiaxp_photinfo_replenish_pmra", "gaiaxp_photinfo_replenish_pmdec",
        "gaiaxp_photinfo_replenish_bp_mag", "gaiaxp_photinfo_replenish_rp_mag",
        "gaiaxp_photinfo_replenish_g_mag", "gaiaxp_photinfo_replenish_ruwe",
        "gaiaxp_photinfo_replenish_excess_factor", "bass_g_g_xpsp", "bass_g_g_err",
        "bass_r_r_xpsp", "bass_r_r_err", "csst_g_g_xpsp", "csst_g_g_err",
        "csst_i_i_xpsp", "csst_i_i_err", "csst_r_r_xpsp", "csst_r_r_err",
        "csst_u_u_xpsp", "csst_u_u_err", "csst_y_y_xpsp", "csst_y_y_err",
        "csst_z_z_xpsp", "csst_z_z_err", "des_g_g_xpsp", "des_g_g_err", "des_i_i_xpsp",
        "des_i_i_err", "des_r_r_xpsp", "des_r_r_err", "des_y_y_xpsp", "des_y_y_err",
        "des_z_z_xpsp", "des_z_z_err", "hipparcos_tycho_b_b_xpsp",
        "hipparcos_tycho_b_b_err", "hipparcos_tycho_hp_hp_bes_xpsp",
        "hipparcos_tycho_hp_hp_bes_err", "hipparcos_tycho_v_v_bes_xpsp",
        "hipparcos_tycho_v_v_bes_err", "jkc_b_b_xpsp", "jkc_b_b_err", "jkc_i_i_xpsp",
        "jkc_i_i_err", "jkc_r_r_xpsp", "jkc_r_r_err", "jkc_u_u_xpsp", "jkc_u_u_err",
        "jkc_v_v_xpsp", "jkc_v_v_err", "jpas_gsdss_gsdss_xpsp", "jpas_gsdss_gsdss_err",
        "jpas_isdss_isdss_xpsp", "jpas_isdss_isdss_err", "jpas_j0378_j0378_xpsp",
        "jpas_j0378_j0378_err", "jpas_j0390_j0390_xpsp", "jpas_j0390_j0390_err",
        "jpas_j0400_j0400_xpsp", "jpas_j0400_j0400_err", "jpas_j0410_j0410_xpsp",
        "jpas_j0410_j0410_err", "jpas_j0420_j0420_xpsp", "jpas_j0420_j0420_err",
        "jpas_j0430_j0430_xpsp", "jpas_j0430_j0430_err", "jpas_j0440_j0440_xpsp",
        "jpas_j0440_j0440_err", "jpas_j0450_j0450_xpsp", "jpas_j0450_j0450_err",
        "jpas_j0460_j0460_xpsp", "jpas_j0460_j0460_err", "jpas_j0470_j0470_xpsp",
        "jpas_j0470_j0470_err", "jpas_j0480_j0480_xpsp", "jpas_j0480_j0480_err",
        "jpas_j0490_j0490_xpsp", "jpas_j0490_j0490_err", "jpas_j0500_j0500_xpsp",
        "jpas_j0500_j0500_err", "jpas_j0510_j0510_xpsp", "jpas_j0510_j0510_err",
        "jpas_j0520_j0520_xpsp", "jpas_j0520_j0520_err", "jpas_j0530_j0530_xpsp",
        "jpas_j0530_j0530_err", "jpas_j0540_j0540_xpsp", "jpas_j0540_j0540_err",
        "jpas_j0550_j0550_xpsp", "jpas_j0550_j0550_err", "jpas_j0560_j0560_xpsp",
        "jpas_j0560_j0560_err", "jpas_j0570_j0570_xpsp", "jpas_j0570_j0570_err",
        "jpas_j0580_j0580_xpsp", "jpas_j0580_j0580_err", "jpas_j0590_j0590_xpsp",
        "jpas_j0590_j0590_err", "jpas_j0600_j0600_xpsp", "jpas_j0600_j0600_err",
        "jpas_j0610_j0610_xpsp", "jpas_j0610_j0610_err", "jpas_j0620_j0620_xpsp",
        "jpas_j0620_j0620_err", "jpas_j0630_j0630_xpsp", "jpas_j0630_j0630_err",
        "jpas_j0640_j0640_xpsp", "jpas_j0640_j0640_err", "jpas_j0650_j0650_xpsp",
        "jpas_j0650_j0650_err", "jpas_j0660_j0660_xpsp", "jpas_j0660_j0660_err",
        "jpas_j0670_j0670_xpsp", "jpas_j0670_j0670_err", "jpas_j0680_j0680_xpsp",
        "jpas_j0680_j0680_err", "jpas_j0690_j0690_xpsp", "jpas_j0690_j0690_err",
        "jpas_j0700_j0700_xpsp", "jpas_j0700_j0700_err", "jpas_j0710_j0710_xpsp",
        "jpas_j0710_j0710_err", "jpas_j0720_j0720_xpsp", "jpas_j0720_j0720_err",
        "jpas_j0730_j0730_xpsp", "jpas_j0730_j0730_err", "jpas_j0740_j0740_xpsp",
        "jpas_j0740_j0740_err", "jpas_j0750_j0750_xpsp", "jpas_j0750_j0750_err",
        "jpas_j0760_j0760_xpsp", "jpas_j0760_j0760_err", "jpas_j0770_j0770_xpsp",
        "jpas_j0770_j0770_err", "jpas_j0780_j0780_xpsp", "jpas_j0780_j0780_err",
        "jpas_j0790_j0790_xpsp", "jpas_j0790_j0790_err", "jpas_j0800_j0800_xpsp",
        "jpas_j0800_j0800_err", "jpas_j0810_j0810_xpsp", "jpas_j0810_j0810_err",
        "jpas_j0820_j0820_xpsp", "jpas_j0820_j0820_err", "jpas_j0830_j0830_xpsp",
        "jpas_j0830_j0830_err", "jpas_j0840_j0840_xpsp", "jpas_j0840_j0840_err",
        "jpas_j0850_j0850_xpsp", "jpas_j0850_j0850_err", "jpas_j0860_j0860_xpsp",
        "jpas_j0860_j0860_err", "jpas_j0870_j0870_xpsp", "jpas_j0870_j0870_err",
        "jpas_j0880_j0880_xpsp", "jpas_j0880_j0880_err", "jpas_j0890_j0890_xpsp",
        "jpas_j0890_j0890_err", "jpas_j0900_j0900_xpsp", "jpas_j0900_j0900_err",
        "jpas_j0910_j0910_xpsp", "jpas_j0910_j0910_err", "jpas_j1007_j1007_xpsp",
        "jpas_j1007_j1007_err", "jpas_rsdss_rsdss_xpsp", "jpas_rsdss_rsdss_err",
        "jpas_u_u_xpsp", "jpas_u_u_err", "jpas_ujava_ujava_xpsp",
        "jpas_ujava_ujava_err", "jplus_gsdss_gsdss_xpsp", "jplus_gsdss_gsdss_err",
        "jplus_isdss_isdss_xpsp", "jplus_isdss_isdss_err", "jplus_j0378_j0378_xpsp",
        "jplus_j0378_j0378_err", "jplus_j0395_j0395_xpsp", "jplus_j0395_j0395_err",
        "jplus_j0410_j0410_xpsp", "jplus_j0410_j0410_err", "jplus_j0430_j0430_xpsp",
        "jplus_j0430_j0430_err", "jplus_j0515_j0515_xpsp", "jplus_j0515_j0515_err",
        "jplus_j0660_j0660_xpsp", "jplus_j0660_j0660_err", "jplus_j0861_j0861_xpsp",
        "jplus_j0861_j0861_err", "jplus_rsdss_rsdss_xpsp", "jplus_rsdss_rsdss_err",
        "jplus_ujava_ujava_xpsp", "jplus_ujava_ujava_err", "jplus_zsdss_zsdss_xpsp",
        "jplus_zsdss_zsdss_err", "kepler_k_k_xpsp", "kepler_k_k_err", "lsst_g_g_xpsp",
        "lsst_g_g_err", "lsst_i_i_xpsp", "lsst_i_i_err", "lsst_r_r_xpsp",
        "lsst_r_r_err", "lsst_u_u_xpsp", "lsst_u_u_err", "lsst_y_y_xpsp",
        "lsst_y_y_err", "lsst_z_z_xpsp", "lsst_z_z_err", "mephisto_g_g_xpsp",
        "mephisto_g_g_err", "mephisto_i_i_xpsp", "mephisto_i_i_err",
        "mephisto_r_r_xpsp", "mephisto_r_r_err", "mephisto_u_u_xpsp",
        "mephisto_u_u_err", "mephisto_v_v_xpsp", "mephisto_v_v_err",
        "mephisto_z_z_xpsp", "mephisto_z_z_err", "ps1_g_g_xpsp", "ps1_g_g_err",
        "ps1_i_i_xpsp", "ps1_i_i_err", "ps1_r_r_xpsp", "ps1_r_r_err", "ps1_y_y_xpsp",
        "ps1_y_y_err", "ps1_z_z_xpsp", "ps1_z_z_err", "sdss_g_g_xpsp", "sdss_g_g_err",
        "sdss_i_i_xpsp", "sdss_i_i_err", "sdss_r_r_xpsp", "sdss_r_r_err",
        "sdss_u_u_xpsp", "sdss_u_u_err", "sdss_z_z_xpsp", "sdss_z_z_err",
        "skymapper_g_g_xpsp", "skymapper_g_g_err", "skymapper_i_i_xpsp",
        "skymapper_i_i_err", "skymapper_r_r_xpsp", "skymapper_r_r_err",
        "skymapper_u_u_xpsp", "skymapper_u_u_err", "skymapper_v_v_xpsp",
        "skymapper_v_v_err", "skymapper_z_z_xpsp", "skymapper_z_z_err",
        "splus_f378_f378_xpsp", "splus_f378_f378_err", "splus_f395_f395_xpsp",
        "splus_f395_f395_err", "splus_f410_f410_xpsp", "splus_f410_f410_err",
        "splus_f430_f430_xpsp", "splus_f430_f430_err", "splus_f515_f515_xpsp",
        "splus_f515_f515_err", "splus_f660_f660_xpsp", "splus_f660_f660_err",
        "splus_f861_f861_xpsp", "splus_f861_f861_err", "splus_g_g_xpsp",
        "splus_g_g_err", "splus_i_i_xpsp", "splus_i_i_err", "splus_r_r_xpsp",
        "splus_r_r_err", "splus_u_u_xpsp", "splus_u_u_err", "splus_z_z_xpsp",
        "splus_z_z_err", "tess_red_red_xpsp", "tess_red_red_err", "ztf_g_g_xpsp",
        "ztf_g_g_err", "ztf_i_i_xpsp", "ztf_i_i_err", "ztf_r_r_xpsp", "ztf_r_r_err",
    ],
    "dr3xpcorr": [  # 17 列: 共享表 11 列 + 改正 XP 光谱 6 列 (flux/c2/c3/caution)
        "gaiaxp_photinfo_replenish_source_id", "gaiaxp_photinfo_replenish_ra",
        "gaiaxp_photinfo_replenish_dec", "gaiaxp_photinfo_replenish_parallax",
        "gaiaxp_photinfo_replenish_pmra", "gaiaxp_photinfo_replenish_pmdec",
        "gaiaxp_photinfo_replenish_ruwe", "gaiaxp_photinfo_replenish_g_mag",
        "gaiaxp_photinfo_replenish_bp_mag", "gaiaxp_photinfo_replenish_rp_mag",
        "gaiaxp_photinfo_replenish_excess_factor",
        "correctedxpspecv1_flux", "correctedxpspecv1_flux_cor",
        "correctedxpspecv1_flux_error", "correctedxpspecv1_c2",
        "correctedxpspecv1_c3", "correctedxpspecv1_caution",
    ],
    # 仅为 parse_csv_rows() 的旧式表头修复路径保留: BEST 没有单一的 ``std`` 表,
    # 因此这些列名不会由任何线上 ``/q`` 路由返回。
    "std": ["std_id", "std_name", "std_ra", "std_dec", "std_mag"],  # 虚拟表: 线上无对应 /q 路由
}

# ==========================================================================
# 7. 星等列映射
# ==========================================================================


# 逐星表的显式星等列映射表: 键是剥掉星表前缀后的列名 (如 ``ps1_rpsf`` -> ``rpsf``),
# 值是规范波段标签。用显式映射而不是"取列名首字母当波段"的启发式, 是为了避免把
# flag / RMS / 改正列误判成星等列。权威来源: 各星表实测列名 (P0-1 修复锚点);
# 消费方: protocol.magnitude_column() 与 models.BestSource.from_row (波段归属的
# 唯一依据, 启发式只在表缺失时兜底)。
CATALOG_MAG_COLUMNS: dict[str, dict[str, str]] = {  # 键=剥前缀后的列名, 值=规范波段标签; 不用首字母启发式
    "ps1": {  # 键是 PSF 星等 (psf), 刻意不收 flag / 改正 / rms 列
        "gpsf": "g", "rpsf": "r", "ipsf": "i", "zpsf": "z", "ypsf": "y",
    },
    "stripe82": {  # 键是 H22 视宁度改正星等 (u/g/r/i/z)
        "u_h22": "u", "g_h22": "g", "r_h22": "r", "i_h22": "i", "z_h22": "z",
    },
    # 2026-09-29 线上核验: 收 ``grvs_mag`` (Gaia G_RVS 分光
    # 星等, 与 G/BP/RP 同为星等列); 流量列 (``phot_*_mean_flux``) 不是
    # 星等, 故意不收。
    "gaia_dr3_18": {  # 只收 G/BP/RP 测光星等 + G_RVS 分光星等
        "phot_g_mean_mag": "g",
        "phot_bp_mean_mag": "bp",
        "phot_rp_mean_mag": "rp",
        "grvs_mag": "grvs",
    },
    # 旧拼写 ``gaia_dr3`` 在本表不另留副本, 归一后命中上方 ``gaia_dr3_18``。
    "landolt": {  # 键混着视宁度星等 (umag/vmag/...) 与 Gaia BP/RP/G
        "umag": "u", "bmag": "b", "vmag": "v", "rmag": "r", "imag": "i",
        "bp_mag": "bp", "rp_mag": "rp", "g_mag": "g",
    },
    "splus_dr4": {  # 键是 ``{band}_pstotal``, 窄带 j0xxx 保持原标签不被改写
        "u_pstotal": "u", "g_pstotal": "g", "r_pstotal": "r", "i_pstotal": "i",
        "z_pstotal": "z", "j0378_pstotal": "j0378", "j0395_pstotal": "j0395",
        "j0410_pstotal": "j0410", "j0430_pstotal": "j0430",
        "j0515_pstotal": "j0515", "j0660_pstotal": "j0660",
        "j0861_pstotal": "j0861",
    },
    "jplus_dr3": {"mag_aper_6_0_final": "mag"},  # 单行表: 6.0 角秒孔径星等, 波段标签就叫 mag
    # 2026-09-29 线上核验: 站点改为 6 波段 PSF 星等 (无单一 psf_mag, 无 source_id)。
    "smss_dr4": {  # 键是 6 个波段 upsf/vpsf/gpsf/rpsf/ipsf/zpsf
        "upsf": "u", "vpsf": "v", "gpsf": "g",
        "rpsf": "r", "ipsf": "i", "zpsf": "z",
    },
    # 2026-09-29 线上核验: 站点重构为 12 波段 ``{{band}}_pstotal``。键用**裸名** ——
    # uss_dr1 的 CSV 响应列名不带 ``uss_dr1_`` 前缀 (站点 datagrid 才带),
    # from_row 剥前缀落空后裸名直接命中本表; 带前缀拼写 (``uss_dr1_u_pstotal``)
    # 剥前缀后同样命中, 两个方向都成立。
    "uss_dr1": {  # 裸名键: 剥前缀与不剥前缀两个方向都能命中本表
        "u_pstotal": "u", "g_pstotal": "g", "r_pstotal": "r",
        "i_pstotal": "i", "z_pstotal": "z",
        "j0378_pstotal": "j0378", "j0395_pstotal": "j0395",
        "j0410_pstotal": "j0410", "j0430_pstotal": "j0430",
        "j0515_pstotal": "j0515", "j0660_pstotal": "j0660",
        "j0861_pstotal": "j0861",
    },
    "scr_galah": {  # 键含原生 SCR 与交叉调查两族, 全部归一到同一套波段标签
        "bapass": "b", "vapass": "v", "zapass": "z", "iapass": "i",
        "rapass": "r", "gapass": "g", "ujkc": "u", "bjkc": "b",
        "vjkc": "v", "rjkc": "r", "ijkc": "i", "gps1": "g", "rps1": "r",
        "ips1": "i", "zps1": "z", "yps1": "y", "usdss": "u", "gsdss": "g",
        "rsdss": "r", "isdss": "i", "zsdss": "z", "usplus": "u",
        "gsplus": "g", "rsplus": "r", "isplus": "i", "zsplus": "z",
        "f378splus": "j0378", "f861splus": "j0861", "gcsst": "g",
        "rztf": "r",
    },
    "scr_lamost": {  # 与 scr_galah 同构: 键集与标签集逐项一致, 只有前缀不同
        "bapass": "b", "vapass": "v", "zapass": "z", "iapass": "i",
        "rapass": "r", "gapass": "g", "ujkc": "u", "bjkc": "b",
        "vjkc": "v", "rjkc": "r", "ijkc": "i", "gps1": "g", "rps1": "r",
        "ips1": "i", "zps1": "z", "yps1": "y", "usdss": "u", "gsdss": "g",
        "rsdss": "r", "isdss": "i", "zsdss": "z", "usplus": "u",
        "gsplus": "g", "rsplus": "r", "isplus": "i", "zsplus": "z",
        "f378splus": "j0378", "f861splus": "j0861", "gcsst": "g",
        "rztf": "r",
    },
    "xpsp": {"g_mag": "g", "bp_mag": "bp", "rp_mag": "rp"},  # 调查测光不进本表, 只留 Gaia 三列
    "dr3xpcorr": {"g_mag": "g", "bp_mag": "bp", "rp_mag": "rp"},  # 改正谱表沿用同一套三列标签
    "std": {"mag": "mag"},  # 虚拟表: 仅供 parse_csv_rows 的旧式表头修复路径
}

# ==========================================================================
# 8. 星等误差列映射
# ==========================================================================


# 逐星表的显式星等误差列映射表: 键同为剥前缀列名, 值为该列所属波段标签。
# 权威来源: 各星表实测误差列命名 (``ps1_gpsf_err`` / ``landolt_e_vmag`` /
# ``splus_dr4_e_u_pstotal``); 消费方: models.BestSource.from_row (填
# magnitude_errors), 与 CATALOG_MAG_COLUMNS 同一套权威来源。
CATALOG_MAG_ERROR_COLUMNS: dict[str, dict[str, str]] = {  # 键=剥前缀误差列名, 值=所属波段; 只收真有误差列的表
    "ps1": {  # 键是 ``{band}psf_err``, 与 CATALOG_MAG_COLUMNS 同构
        "gpsf_err": "g", "rpsf_err": "r", "ipsf_err": "i",
        "zpsf_err": "z", "ypsf_err": "y",
    },
    "landolt": {  # 键是 ``e_{band}mag`` 视宁度误差, 不含 Gaia BP/RP 误差
        "e_umag": "u", "e_bmag": "b", "e_vmag": "v",
        "e_rmag": "r", "e_imag": "i",
    },
    "splus_dr4": {  # 键是 ``e_{band}_pstotal``, 窄带误差同样逐波段登记
        "e_u_pstotal": "u", "e_g_pstotal": "g", "e_r_pstotal": "r",
        "e_i_pstotal": "i", "e_z_pstotal": "z",
        "e_j0378_pstotal": "j0378", "e_j0395_pstotal": "j0395",
        "e_j0410_pstotal": "j0410", "e_j0430_pstotal": "j0430",
        "e_j0515_pstotal": "j0515", "e_j0660_pstotal": "j0660",
        "e_j0861_pstotal": "j0861",
    },
    # 2026-09-29 线上核验: uss_dr1 按波段重构后每波段有 ``{{band}}_err_pstotal``
    # (裸名, 同 CATALOG_MAG_COLUMNS.uss_dr1 的双向命中约定)。
    "uss_dr1": {  # 裸名键: 与本表 uss_dr1 条目同一套双向命中约定
        "u_err_pstotal": "u", "g_err_pstotal": "g", "r_err_pstotal": "r",
        "i_err_pstotal": "i", "z_err_pstotal": "z",
        "j0378_err_pstotal": "j0378", "j0395_err_pstotal": "j0395",
        "j0410_err_pstotal": "j0410", "j0430_err_pstotal": "j0430",
        "j0515_err_pstotal": "j0515", "j0660_err_pstotal": "j0660",
        "j0861_err_pstotal": "j0861",
    },
}

# ==========================================================================
# 9. 质量列映射
# ==========================================================================


# 逐星表真实发布的质量列: 权威来源为各星表可用过滤列实测。消费方:
# quality_column() -> build_query_form() 的 ``min_snr``/``max_fwhm``/
# ``class_star_min`` 流畅接口。
#
# 流畅构造器的这三个过滤不得凭空发明 ``snr`` / ``fwhm`` / ``class_star`` 列名
# —— 没有任何星表发布这些列, 那样过滤条件就约束在幻影列上, 静默匹配 0 行。
# 缺失即 fail-closed (见 quality_column 的 Raises)。
QUALITY_COLUMNS: dict[str, dict[str, str]] = {  # 键=流畅接口名, 值=站点真实发布的过滤列; 空表即 fail-closed
    "ps1": {"class_star": "class_star"},  # 唯一可用质量列: 恒星形态判据
    "stripe82": {},  # 该表不发布质量列: 走流畅过滤即拒绝, 不静默匹配 0 行
    "gaia_dr3_18": {},  # 同上: 天体测量列不能当质量过滤用
    "jplus_dr3": {},  # 单孔径星等表: 无形态/信噪列, 流畅过滤走拒绝而非匹配 0 行
    "smss_dr4": {},  # 定标星等表: 只发布 6 个波段 PSF 星等, 无形态判据
    "landolt": {},  # 标准星表: 视宁度星等已定标好, 站点不再另发过滤列
    "uss_dr1": {},  # 12 波段 pstotal 表: 同样只给测光值, 无质量列
    "splus_dr4": {"snr": "s2n_det_auto"},  # 接口叫 snr, 站点列名是 s2n_det_auto
    "scr_galah": {},  # 标准星表: 该组三张表 (含 xpsp) 一律 fail-closed
    "scr_lamost": {},  # 同上: 标准星无形态/信噪列可过滤
    "xpsp": {},  # 光谱拟合测光表: 无 class_star/snr, 过滤请求一律拒绝
    "dr3xpcorr": {},  # 改正谱表: 只发 flux/c2/c3 谱拟合列, 无质量列
    "gaia_dr3": {"class_star": "class_star"},  # 旧拼写入口: 归一后指向上方 gaia_dr3_18
}
