import {expect,test,type Page} from "@playwright/test";
import {installApiMock} from "./fixtures";

async function signIn(page:Page){
  await page.goto("/");
  await page.getByTestId("auth-email").fill("browser@example.com");
  await page.getByTestId("auth-password").fill("browser-test-password");
  await page.getByTestId("auth-submit").click();
  await expect(page.getByRole("heading",{name:"Today",exact:true})).toBeVisible();
}

async function expectNoHorizontalOverflow(page:Page){
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+1)).toBe(true);
}

test("Research, Portfolio, Ask, Decisions, and Market Climate remain usable at representative responsive widths",async({page})=>{
  await installApiMock(page);
  await signIn(page);
  for(const width of [375,390,430,768]){
    await page.setViewportSize({width,height:900});

    await page.goto("/research?ticker=AAPL");
    await expect(page.getByRole("heading",{name:/AAPL Apple Inc\./})).toBeVisible();
    await expect(page.getByText("What does it do?",{exact:true})).toBeVisible();
    await expectNoHorizontalOverflow(page);

    await page.goto("/portfolio");
    await expect(page.getByRole("heading",{name:"What needs attention in this portfolio?"})).toBeVisible();
    await page.getByRole("button",{name:"Edit holdings"}).click();
    await expect(page.locator("tbody tr")).toHaveCount(2);
    await expectNoHorizontalOverflow(page);

    await page.goto("/ask");
    await expect(page.locator(".ask-chat-pane")).toBeVisible();
    await expectNoHorizontalOverflow(page);

    await page.goto("/decisions");
    await expect(page.getByText("Choose a security",{exact:true})).toBeVisible();
    await expect(page.getByRole("button",{name:/AAPL.*Holding/})).toBeVisible();
    await expectNoHorizontalOverflow(page);

    await page.goto("/market-climate");
    await expect(page.getByRole("heading",{name:"Mixed, transitionary conditions"})).toBeVisible();
    await expect(page.getByText("Prediction markets and upcoming events")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }
});
