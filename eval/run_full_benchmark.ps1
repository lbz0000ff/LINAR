$env:OPENAI_API_KEY = $env:DEEPSEEK_API_KEY
$env:OPENAI_BASE_URL = "https://api.deepseek.com/v1"
$env:LLM_BACKEND = "openai"
$env:RACE_MODEL = "deepseek-v4-pro"
$env:PYTHONENCODING = "utf-8"

cd deep_research_bench
python3.exe -u deepresearch_bench_race.py "linar" --raw_data_dir data/test_data/raw_data --max_workers 1 --query_file data/prompt_data/query.jsonl --output_dir results/race/linar