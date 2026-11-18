# Reults from test_paragraph.txt:
> WER score is the number of words missed by the model. Lower is therefore better.\
> Best model found is `am_fenrir` with 11.5% 3x


WER % (lower = more intelligible), best first by mean over speeds >= 1.5x:
| voice       | wer_2x | wer_2.5x | wer_3x |
|-------------|--------|----------|--------|
| af_heart    | 0.0764 | 0.1401   | 0.2357 |
| af_bella    | 0.051  | 0.1146   | 0.1847 |
| af_nicole   | 0.1083 | 0.2803   | 0.4968 |
| af_sarah    | 0.0828 | 0.242    | 0.2293 |
| af_sky      | 0.0701 | 0.1529   | 0.2229 |
| af_alloy    | 0.0382 | 0.1019   | 0.1975 |
| af_aoede    | 0.0892 | 0.1529   | 0.2038 |
| af_jessica  | 0.0573 | 0.1656   | 0.1656 |
| af_kore     | 0.0637 | 0.2229   | 0.2229 |
| af_nova     | 0.0828 | 0.1592   | 0.1465 |
| af_river    | 0.0382 | 0.1783   | 0.1847 |
| am_adam     | 0.051  | 0.1338   | 0.1783 |
| am_michael  | 0.0701 | 0.1401   | 0.2484 |
| am_echo     | 0.0701 | 0.1274   | 0.1656 |
| am_eric     | 0.0892 | 0.2357   | 0.2866 |
| am_fenrir   | 0.0382 | 0.1019   | 0.1146 |
| am_liam     | 0.0382 | 0.1019   | 0.1274 |
| am_onyx     | 0.0764 | 0.1338   | 0.2803 |
| am_puck     | 0.0573 | 0.1529   | 0.2293 |
| am_santa    | 0.0573 | 0.1274   | 0.1656 |
| bf_emma     | 0.0701 | 0.1465   | 0.172  |
| bf_isabella | 0.0828 | 0.1338   | 0.2166 |
| bf_alice    | 0.0828 | 0.1911   | 0.2803 |
| bf_lily     | 0.0637 | 0.1338   | 0.2484 |
| bm_george   | 0.0637 | 0.2166   | 0.2484 |
| bm_lewis    | 0.1338 | 0.242    | 0.3503 |
| bm_daniel   | 0.0637 | 0.1656   | 0.2229 |
| bm_fable    | 0.0701 | 0.121    | 0.2038 |


```txt
  af_bella        2x  WER   5.1%  ( 35.3s audio)
  af_bella      2.5x  WER  11.5%  ( 31.2s audio)
  af_bella        3x  WER  18.5%  ( 29.8s audio)
voices/af_nicole.pt: downloading bytes: ███████████████████████████████████████████████████████████|  365kB, 35.8kB/s
voices/af_nicole.pt: reconstructing file: 100%|███████████████████████████████████████████|  523kB /  523kB, 51.4kB/s
  af_nicole       2x  WER  10.8%  ( 50.4s audio)
  af_nicole     2.5x  WER  28.0%  ( 42.5s audio)
  af_nicole       3x  WER  49.7%  ( 37.9s audio)
voices/af_sarah.pt: downloading bytes: ████████████████████████████████████████████████████████████|  374kB, 36.8kB/s
voices/af_sarah.pt: reconstructing file: 100%|████████████████████████████████████████████|  523kB /  523kB, 51.5kB/s
  af_sarah        2x  WER   8.3%  ( 34.8s audio)
  af_sarah      2.5x  WER  24.2%  ( 31.6s audio)
  af_sarah        3x  WER  22.9%  ( 30.1s audio)
voices/af_sky.pt: downloading bytes: ██████████████████████████████████████████████████████████████|  369kB, 36.3kB/s
voices/af_sky.pt: reconstructing file: 100%|██████████████████████████████████████████████|  523kB /  523kB, 51.5kB/s
  af_sky          2x  WER   7.0%  ( 33.1s audio)
  af_sky        2.5x  WER  15.3%  ( 30.4s audio)
  af_sky          3x  WER  22.3%  ( 29.3s audio)
voices/af_alloy.pt: downloading bytes: ████████████████████████████████████████████████████████████|  379kB, 35.8kB/s
voices/af_alloy.pt: reconstructing file: 100%|████████████████████████████████████████████|  523kB /  523kB, 49.6kB/s
  af_alloy        2x  WER   3.8%  ( 31.5s audio)
  af_alloy      2.5x  WER  10.2%  ( 29.3s audio)
  af_alloy        3x  WER  19.7%  ( 28.5s audio)
voices/af_aoede.pt: downloading bytes: ████████████████████████████████████████████████████████████|  392kB, 38.5kB/s
voices/af_aoede.pt: reconstructing file: 100%|████████████████████████████████████████████|  523kB /  523kB, 51.4kB/s
  af_aoede        2x  WER   8.9%  ( 33.2s audio)
  af_aoede      2.5x  WER  15.3%  ( 30.4s audio)
  af_aoede        3x  WER  20.4%  ( 29.0s audio)
voices/af_jessica.pt: downloading bytes: ██████████████████████████████████████████████████████████|  380kB, 37.0kB/s
voices/af_jessica.pt: reconstructing file: 100%|██████████████████████████████████████████|  523kB /  523kB, 51.0kB/s
  af_jessica      2x  WER   5.7%  ( 31.1s audio)
  af_jessica    2.5x  WER  16.6%  ( 29.2s audio)
  af_jessica      3x  WER  16.6%  ( 28.3s audio)
voices/af_kore.pt: downloading bytes: █████████████████████████████████████████████████████████████|  405kB, 39.8kB/s
voices/af_kore.pt: reconstructing file: 100%|█████████████████████████████████████████████|  523kB /  523kB, 51.5kB/s
  af_kore         2x  WER   6.4%  ( 32.5s audio)
  af_kore       2.5x  WER  22.3%  ( 29.4s audio)
  af_kore         3x  WER  22.3%  ( 28.4s audio)
voices/af_nova.pt: downloading bytes: █████████████████████████████████████████████████████████████|  385kB, 37.5kB/s
voices/af_nova.pt: reconstructing file: 100%|█████████████████████████████████████████████|  523kB /  523kB, 51.0kB/s
  af_nova         2x  WER   8.3%  ( 31.5s audio)
  af_nova       2.5x  WER  15.9%  ( 29.3s audio)
  af_nova         3x  WER  14.6%  ( 28.6s audio)
voices/af_river.pt: downloading bytes: ████████████████████████████████████████████████████████████|  385kB, 36.9kB/s
voices/af_river.pt: reconstructing file: 100%|████████████████████████████████████████████|  523kB /  523kB, 50.4kB/s
  af_river        2x  WER   3.8%  ( 30.9s audio)
  af_river      2.5x  WER  17.8%  ( 28.8s audio)
  af_river        3x  WER  18.5%  ( 28.2s audio)
  am_adam         2x  WER   5.1%  ( 33.6s audio)
  am_adam       2.5x  WER  13.4%  ( 30.6s audio)
  am_adam         3x  WER  17.8%  ( 29.2s audio)
voices/am_michael.pt: downloading bytes: ██████████████████████████████████████████████████████████|  360kB, 35.4kB/s
voices/am_michael.pt: reconstructing file: 100%|██████████████████████████████████████████|  523kB /  523kB, 51.4kB/s
  am_michael      2x  WER   7.0%  ( 36.6s audio)
  am_michael    2.5x  WER  14.0%  ( 32.1s audio)
  am_michael      3x  WER  24.8%  ( 30.1s audio)
voices/am_echo.pt: downloading bytes: █████████████████████████████████████████████████████████████|  376kB, 36.7kB/s
voices/am_echo.pt: reconstructing file: 100%|█████████████████████████████████████████████|  523kB /  523kB, 51.0kB/s
  am_echo         2x  WER   7.0%  ( 31.7s audio)
  am_echo       2.5x  WER  12.7%  ( 29.2s audio)
  am_echo         3x  WER  16.6%  ( 28.6s audio)
voices/am_eric.pt: downloading bytes: █████████████████████████████████████████████████████████████|  377kB, 37.0kB/s
voices/am_eric.pt: reconstructing file: 100%|█████████████████████████████████████████████|  523kB /  523kB, 51.4kB/s
  am_eric         2x  WER   8.9%  ( 30.8s audio)
  am_eric       2.5x  WER  23.6%  ( 29.0s audio)
  am_eric         3x  WER  28.7%  ( 28.4s audio)
voices/am_fenrir.pt: downloading bytes: ███████████████████████████████████████████████████████████|  404kB, 38.5kB/s
voices/am_fenrir.pt: reconstructing file: 100%|███████████████████████████████████████████|  523kB /  523kB, 49.9kB/s
  am_fenrir       2x  WER   3.8%  ( 32.4s audio)
  am_fenrir     2.5x  WER  10.2%  ( 29.4s audio)
  am_fenrir       3x  WER  11.5%  ( 28.3s audio)
voices/am_liam.pt: downloading bytes: █████████████████████████████████████████████████████████████|  388kB, 37.6kB/s
voices/am_liam.pt: reconstructing file: 100%|█████████████████████████████████████████████|  523kB /  523kB, 50.9kB/s
  am_liam         2x  WER   3.8%  ( 31.4s audio)
  am_liam       2.5x  WER  10.2%  ( 29.2s audio)
  am_liam         3x  WER  12.7%  ( 28.6s audio)
voices/am_onyx.pt: downloading bytes: █████████████████████████████████████████████████████████████|  379kB, 37.0kB/s
voices/am_onyx.pt: reconstructing file: 100%|█████████████████████████████████████████████|  523kB /  523kB, 51.0kB/s
  am_onyx         2x  WER   7.6%  ( 31.7s audio)
  am_onyx       2.5x  WER  13.4%  ( 29.6s audio)
  am_onyx         3x  WER  28.0%  ( 28.7s audio)
voices/am_puck.pt: downloading bytes: █████████████████████████████████████████████████████████████|  404kB, 39.4kB/s
voices/am_puck.pt: reconstructing file: 100%|█████████████████████████████████████████████|  523kB /  523kB, 51.0kB/s
  am_puck         2x  WER   5.7%  ( 31.8s audio)
  am_puck       2.5x  WER  15.3%  ( 29.4s audio)
  am_puck         3x  WER  22.9%  ( 28.5s audio)
voices/am_santa.pt: downloading bytes: ████████████████████████████████████████████████████████████|  388kB, 36.8kB/s
voices/am_santa.pt: reconstructing file: 100%|████████████████████████████████████████████|  523kB /  523kB, 50.3kB/s
  am_santa        2x  WER   5.7%  ( 33.6s audio)
  am_santa      2.5x  WER  12.7%  ( 30.2s audio)
  am_santa        3x  WER  16.6%  ( 28.8s audio)
  bf_emma         2x  WER   7.0%  ( 34.0s audio)
  bf_emma       2.5x  WER  14.6%  ( 31.3s audio)
  bf_emma         3x  WER  17.2%  ( 30.0s audio)
voices/bf_isabella.pt: downloading bytes: █████████████████████████████████████████████████████████|  348kB, 33.9kB/s
voices/bf_isabella.pt: reconstructing file: 100%|█████████████████████████████████████████|  523kB /  523kB, 51.0kB/s
  bf_isabella     2x  WER   8.3%  ( 33.5s audio)
  bf_isabella   2.5x  WER  13.4%  ( 30.9s audio)
  bf_isabella     3x  WER  21.7%  ( 29.6s audio)
voices/bf_alice.pt: downloading bytes: ████████████████████████████████████████████████████████████|  374kB, 36.7kB/s
voices/bf_alice.pt: reconstructing file: 100%|████████████████████████████████████████████|  523kB /  523kB, 51.4kB/s
  bf_alice        2x  WER   8.3%  ( 32.9s audio)
  bf_alice      2.5x  WER  19.1%  ( 29.7s audio)
  bf_alice        3x  WER  28.0%  ( 28.7s audio)
voices/bf_lily.pt: downloading bytes: █████████████████████████████████████████████████████████████|  375kB, 36.5kB/s
voices/bf_lily.pt: reconstructing file: 100%|█████████████████████████████████████████████|  523kB /  523kB, 51.0kB/s
  bf_lily         2x  WER   6.4%  ( 32.8s audio)
  bf_lily       2.5x  WER  13.4%  ( 29.8s audio)
  bf_lily         3x  WER  24.8%  ( 28.8s audio)
voices/bm_george.pt: downloading bytes: ███████████████████████████████████████████████████████████|  368kB, 36.1kB/s
voices/bm_george.pt: reconstructing file: 100%|███████████████████████████████████████████|  523kB /  523kB, 51.4kB/s
  bm_george       2x  WER   6.4%  ( 36.0s audio)
  bm_george     2.5x  WER  21.7%  ( 31.9s audio)
  bm_george       3x  WER  24.8%  ( 30.1s audio)
voices/bm_lewis.pt: downloading bytes: ████████████████████████████████████████████████████████████|  371kB, 35.7kB/s
voices/bm_lewis.pt: reconstructing file: 100%|████████████████████████████████████████████|  523kB /  523kB, 51.0kB/s
  bm_lewis        2x  WER  13.4%  ( 36.3s audio)
  bm_lewis      2.5x  WER  24.2%  ( 31.9s audio)
  bm_lewis        3x  WER  35.0%  ( 30.2s audio)
voices/bm_daniel.pt: downloading bytes: ███████████████████████████████████████████████████████████|  369kB, 36.0kB/s
voices/bm_daniel.pt: reconstructing file: 100%|███████████████████████████████████████████|  523kB /  523kB, 51.1kB/s
  bm_daniel       2x  WER   6.4%  ( 31.4s audio)
  bm_daniel     2.5x  WER  16.6%  ( 29.4s audio)
  bm_daniel       3x  WER  22.3%  ( 28.6s audio)
voices/bm_fable.pt: downloading bytes: ████████████████████████████████████████████████████████████|  376kB, 37.0kB/s
voices/bm_fable.pt: reconstructing file: 100%|████████████████████████████████████████████|  523kB /  523kB, 51.5kB/s
  bm_fable        2x  WER   7.0%  ( 31.9s audio)
  bm_fable      2.5x  WER  12.1%  ( 29.9s audio)
  bm_fable        3x  WER  20.4%  ( 29.0s audio)
```
