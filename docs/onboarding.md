# Onboarding
This file explains how the onboarding endpoint functions and why design decisions were made.

The onboarding is the next process that kicks off after a new user has signed up, verified their account and logged in for the first time. Here is where the user sets ups their weekly workout routine.

## Important Objects
- **Workout**: This represents a day of the week and what muscle group the user trains on that day, See [WorkoutCreate schema](../app/schemas/workout.py)

- **Workout exercise**: This represents an specific exercise that the user performs for a workout. This means a many to one relationships between workout exercises and workouts. See [WorkoutExercise schema](../app/schemas/workout_exercise.py)

- **Onboarding**: This represents data received from the onboarding client interfaces. For now the onboarding is just for creating workouts and exercises, new data may be added to it in the future. See [Onboarding schema](../app/schemas/onboarding.py). All of the data is saved with one call to the API endpoint `/api/onboarding/workout`

## How it works
On the client side, the user creates workouts and exercises for each workout. All of these are sent as a list of objects. Each object in the list contains a workout and a list of exercises. 

Inside the onboarding router function, we are simply looping through the list of objects, saving each workout to the DB and then saving the exercises associated with the workout.