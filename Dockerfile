FROM python:3.11

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app


# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy project and env file
COPY . .
# COPY .env .

# Set required environment variables
ENV EMAIL_ADDRESS="zainkiyani682@gmail.com"
ENV EMAIL_HOST_PASSWORD="jipg eshv sqbb yiah"
ENV SECRET_KEY="u$2gcbz61ufvk!v0^gqz#wulu&u6nfg@6fp#sw9w(qbwx#4n_$"
ENV ENVIORNMENT="production"

RUN python manage.py collectstatic --noinput
EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
