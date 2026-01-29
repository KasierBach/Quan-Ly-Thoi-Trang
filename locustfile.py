from locust import HttpUser, task, between
import random

class WebsiteUser(HttpUser):
    wait_time = between(1, 5)

    @task(3)
    def view_home(self):
        self.client.get("/")

    @task(2)
    def view_products(self):
        self.client.get("/products")

    @task(1)
    def view_product_detail(self):
        # Assuming product IDs 1-10 exist
        product_id = random.randint(1, 10)
        self.client.get(f"/product/{product_id}")

    # @task(1)
    # def login(self):
    #     self.client.post("/auth/login", {
    #         "email": "test@example.com",
    #         "password": "password"
    #     })
