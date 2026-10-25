# target_type/photometry_region — 测光天区切片

- 触发词: "ps1 区域 / stripe82 / 深场"
- 处理: `download_region(downloader, ra_center, dec_center, radius_arcsec=600.0,
  catalog="ps1", bands=None, ...)` — **首参是 downloader 实例**, 半径口径 arcsec;
  与 `BestQuery.cone(ra, dec, radius_deg)` 的 deg 口径差异必须双处断言。
- 一票否决: 无约束的"全表导出"请求直接拒绝。
