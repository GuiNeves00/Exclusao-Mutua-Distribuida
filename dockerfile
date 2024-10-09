FROM python:3.9-slim

WORKDIR /app

COPY mutual_exclusion.py /app/
COPY recurso.txt /app/

RUN pip install filelock

CMD ["python", "mutual_exclusion.py"]
