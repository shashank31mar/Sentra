FROM nginx:alpine

# Create health endpoints for both /health and /v1/health
RUN mkdir -p /usr/share/nginx/html/v1 && \
    echo '{"status":"healthy","service":"dummy"}' > /usr/share/nginx/html/health && \
    echo '{"status":"healthy","service":"dummy"}' > /usr/share/nginx/html/v1/health

# Configure nginx to respond on port 8080 and serve JSON
RUN sed -i 's/listen       80;/listen       8080;/g' /etc/nginx/conf.d/default.conf && \
    sed -i '/location \/ {/a \        default_type application/json;' /etc/nginx/conf.d/default.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
