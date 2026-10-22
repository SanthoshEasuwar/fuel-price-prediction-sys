
from locust import HttpUser, task, between


class FuelPriceUser(HttpUser):
    # Wait 1–3 seconds between requests
    wait_time = between(1, 3)

    @task
    def open_homepage(self):
        with self.client.get(
            "/",
            name="Homepage",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(
                    f"Unexpected HTTP status: {response.status_code}"
                )
