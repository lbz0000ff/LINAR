python3 -m piper.train fit \
  --data.voice_name "Firefly" \
  --data.csv_path /root/firefly/dataset/metadata.csv \
  --data.audio_dir /root/firefly/dataset/wav/ \
  --model.sample_rate 22050 \
  --data.espeak_voice "zh" \
  --data.cache_dir /root/firefly/cache/ \
  --data.config_path /root/firefly/config.json \
  --data.batch_size 32 \
  --ckpt_path /root/firefly/finetune.ckpt  # optional but highly recommended
