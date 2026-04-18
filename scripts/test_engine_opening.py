from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


URL = "http://127.0.0.1:8787"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        errors = []

        page.on("console", lambda msg: print(f"[console:{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))

        page.goto(URL)
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name="Configure").click()
        page.get_by_role("button", name="White").click()
        page.get_by_role("button", name="Play vs Engine").click()

        page.wait_for_load_state("networkidle")
        page.wait_for_selector("text=Black's turn", timeout=5000)

        try:
          page.wait_for_selector("text=White's turn", timeout=5000)
        except PlaywrightTimeoutError as exc:
          page.screenshot(path="engine-opening-failure.png", full_page=True)
          raise RuntimeError(
              "Engine did not finish the opening move within 5s. "
              "Saved screenshot to engine-opening-failure.png"
          ) from exc

        if errors:
            raise RuntimeError("Browser errors detected:\n" + "\n".join(errors))

        print("Engine opening test passed.")
        browser.close()


if __name__ == "__main__":
    main()
