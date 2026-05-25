#!/bin/bash
# run.sh

mkdir -p cookies input output Proxy browser-profile

case "$1" in
    cookie)
        echo "🍪 Lấy cookie theo quốc gia..."
        docker run --rm -it \
            --shm-size=2g \
            -v $(pwd):/app \
            -v $(pwd)/cookies:/app/cookies \
            -v $(pwd)/Proxy:/app/Proxy \
            -v $(pwd)/input:/app/input \
            amazon-scraper python cookie_fetcher.py
        ;;
    scrape)
        echo "📦 Scrape dữ liệu..."
        docker run --rm -it \
            -v $(pwd):/app \
            -v $(pwd)/input:/app/input \
            -v $(pwd)/output:/app/output \
            -v $(pwd)/cookies:/app/cookies \
            -v $(pwd)/Proxy:/app/Proxy \
            amazon-scraper python main.py
        ;;
    build)
        echo "🔨 Build lại image..."
        docker build --no-cache -t amazon-scraper .
        ;;
    shell)
        echo "🐚 Mở shell..."
        docker run --rm -it \
            -v $(pwd):/app \
            amazon-scraper /bin/bash
        ;;
    *)
        echo "Cách dùng: ./run.sh [cookie|scrape|build|shell]"
        ;;
esac