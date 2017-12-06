FROM alpine:latest
LABEL maintainer "Noble Code"

RUN apk add --no-cache dropbear && mkdir /etc/dropbear
COPY entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
