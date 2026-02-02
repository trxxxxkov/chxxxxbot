FROM docker:cli

RUN apk add --no-cache git bash

COPY autodeploy.sh /autodeploy.sh
RUN chmod +x /autodeploy.sh

CMD ["/autodeploy.sh"]
