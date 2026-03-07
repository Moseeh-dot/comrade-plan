# Comrade Plan

A simple student budgeting web application designed to help university students manage their allowance and avoid overspending.

## Overview

Comrade Plan helps students track their daily spending based on their total allowance and the number of days until the next allowance. The system calculates how much a student can spend per day and warns when they exceed their limit.

This project was built using Python and Flask with an SQLite database.

## Features

* Student registration and login
* Secure password storage
* Allowance tracking
* Daily spending limit calculation
* Spending monitoring
* Warning when daily spending is exceeded
* Simple and clean web interface

## Technology Stack

* Python
* Flask
* SQLite
* HTML5
* CSS3

## Project Structure

```
comrade-plan/
│
├── app.py
├── requirements.txt
├── budget.db
│
├── templates/
│   ├── index.html
│   ├── register.html
│   └── dashboard.html
│
└── static/
    └── style.css
```

## Installation

1. Clone the repository

```
git clone https://github.com/Moseeh-dot/comrade-plan.git
cd comrade-plan
```

2. Install dependencies

```
pip install -r requirements.txt
```

3. Run the application

```
python app.py
```

4. Open your browser and visit

```
http://127.0.0.1:5000
```

## How It Works

1. A student registers with their email and password.
2. They enter their total allowance and the number of days until the next allowance.
3. The system calculates the daily spending limit.
4. Each time the student records spending, the app checks if the limit is exceeded.
5. If the limit is exceeded, the system displays a warning.

## Future Improvements

* Mobile-friendly interface
* Spending analytics and charts
* Expense categories
* Notifications when the daily limit is reached
* Cloud database support
* Android mobile application

## Purpose

Many students spend their allowance too quickly and struggle financially before the next allowance arrives. Comrade Plan aims to help students develop better financial discipline and budgeting habits.

## License

This project is open-source and available for learning and educational purposes.

## Author

Mose Munene

