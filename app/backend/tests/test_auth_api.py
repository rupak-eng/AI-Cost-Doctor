"""Auth API tests: signup -> login -> me, refresh rotation, failure modes."""
import uuid


def _email():
    return f"test-{uuid.uuid4().hex[:12]}@example.com"


class TestSignupLoginMe:
    def test_full_flow(self, client):
        email = _email()
        # signup
        r = client.post("/api/v1/auth/signup", json={
            "email": email, "password": "correct-horse-9", "org_name": "Acme AI"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"] and body["refresh_token"]
        assert body["user"]["email"] == email
        assert body["user"]["role"] == "owner"
        assert body["org"]["name"] == "Acme AI"
        assert body["project"]["name"] == "Default project"

        # login
        r = client.post("/api/v1/auth/login",
                        json={"email": email, "password": "correct-horse-9"})
        assert r.status_code == 200, r.text
        login_body = r.json()
        assert login_body["user"]["id"] == body["user"]["id"]
        token = login_body["access_token"]

        # me
        r = client.get("/api/v1/auth/me",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["user"]["email"] == email
        assert me["org"]["id"] == body["org"]["id"]
        assert len(me["projects"]) == 1

    def test_duplicate_signup_409(self, client):
        email = _email()
        payload = {"email": email, "password": "correct-horse-9", "org_name": "Acme"}
        assert client.post("/api/v1/auth/signup", json=payload).status_code == 201
        r = client.post("/api/v1/auth/signup", json=payload)
        assert r.status_code == 409

    def test_wrong_password_401(self, client):
        email = _email()
        client.post("/api/v1/auth/signup", json={
            "email": email, "password": "correct-horse-9", "org_name": "Acme"})
        r = client.post("/api/v1/auth/login",
                        json={"email": email, "password": "wrong-password"})
        assert r.status_code == 401

    def test_unknown_email_401(self, client):
        r = client.post("/api/v1/auth/login", json={
            "email": _email(), "password": "whatever-123"})
        assert r.status_code == 401

    def test_me_without_token_401(self, client):
        assert client.get("/api/v1/auth/me").status_code in (401, 403)

    def test_me_with_garbage_token_401(self, client):
        r = client.get("/api/v1/auth/me",
                       headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401

    def test_password_too_short_422(self, client):
        r = client.post("/api/v1/auth/signup", json={
            "email": _email(), "password": "short", "org_name": "Acme"})
        assert r.status_code == 422


class TestRefreshRotation:
    def test_refresh_rotates_and_revokes(self, client):
        email = _email()
        signup = client.post("/api/v1/auth/signup", json={
            "email": email, "password": "correct-horse-9", "org_name": "Acme"}).json()
        refresh_1 = signup["refresh_token"]

        r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_1})
        assert r.status_code == 200, r.text
        pair_2 = r.json()
        assert pair_2["access_token"] and pair_2["refresh_token"]
        assert pair_2["refresh_token"] != refresh_1

        # The old refresh token is revoked on use: replay must fail.
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_1})
        assert r.status_code == 401

        # The new one works.
        r = client.post("/api/v1/auth/refresh",
                        json={"refresh_token": pair_2["refresh_token"]})
        assert r.status_code == 200

    def test_refresh_with_garbage_401(self, client):
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"})
        assert r.status_code == 401

    def test_new_access_token_works(self, client):
        email = _email()
        signup = client.post("/api/v1/auth/signup", json={
            "email": email, "password": "correct-horse-9", "org_name": "Acme"}).json()
        pair = client.post("/api/v1/auth/refresh",
                           json={"refresh_token": signup["refresh_token"]}).json()
        r = client.get("/api/v1/auth/me",
                       headers={"Authorization": f"Bearer {pair['access_token']}"})
        assert r.status_code == 200
        assert r.json()["user"]["email"] == email
