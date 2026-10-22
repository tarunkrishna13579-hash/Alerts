# 53-company coverage audit

This table distinguishes configured company entries from feeds that actually returned jobs. It reflects a full 53-company self-test on 2026-10-22 UTC, plus targeted source rechecks for Pegasystems, Commvault, and Synchrony afterward. The targeted checks do not replace rerunning the full self-test after deployment.

**Coverage at audit:** 28 companies have a direct source that returned listings; 25 still need a working source or an optional secondary provider. A successful page probe alone is not a validated job feed. HTTP 403 means that the audit request was blocked; behavior can differ on the GitHub runner.

| # | Company | Official careers page | Latest source result | Page probe |
|---:|---|---|---|---|
| 1 | Salesforce | [https://careers.salesforce.com/en/jobs/?country=India](https://careers.salesforce.com/en/jobs/?country=India) | **GAP** — No supported public feed discovered (no supported feed found on the official careers page) | HTTP 200 |
| 2 | ServiceNow | [https://careers.servicenow.com/locations/apj/india/](https://careers.servicenow.com/locations/apj/india/) | **GAP** — No supported public feed discovered (no supported feed found on the official careers page) | HTTP 403 |
| 3 | Cisco | [https://careers.cisco.com/global/en/india/](https://careers.cisco.com/global/en/india/) | **VALIDATED** — Workday: 60 listings | HTTP 200; ATS marker: workday, phenom |
| 4 | Visa | [https://corporate.visa.com/en/jobs](https://corporate.visa.com/en/jobs) | **VALIDATED** — Workday: 40 listings | HTTP 200; ATS marker: workday |
| 5 | Mastercard | [https://careers.mastercard.com/](https://careers.mastercard.com/) | **VALIDATED** — Workday: 9 listings | HTTP 200; ATS marker: workday, phenom |
| 6 | PayPal | [https://www.paypal.com/us/webapps/mpp/jobs](https://www.paypal.com/us/webapps/mpp/jobs) | **GAP** — Eightfold candidate returned no usable listings in the full run | HTTP 403 |
| 7 | SAP | [https://careers.sap.com/go/India/8807201/](https://careers.sap.com/go/India/8807201/) | **VALIDATED** — Official career page: 25 listings | HTTP 200; ATS marker: successfactors |
| 8 | Pegasystems | [https://www.pega.com/about/careers](https://www.pega.com/about/careers) | **VALIDATED** — Official career page: 23 listings (rechecked after full run) | HTTP 200 |
| 9 | Thomson Reuters | [https://www.thomsonreuters.com/en/careers.html](https://www.thomsonreuters.com/en/careers.html) | **VALIDATED** — Workday: 40 listings | HTTP 200; ATS marker: workday |
| 10 | Target | [https://corporate.target.com/careers](https://corporate.target.com/careers) | **VALIDATED** — Workday: 40 listings | HTTP 200; ATS marker: workday |
| 11 | Experian | [https://jobs.experian.com/](https://jobs.experian.com/) | **VALIDATED** — Official career page: 12 listings | HTTP 200 |
| 12 | Walmart Global Tech | [https://careers.walmart.com/](https://careers.walmart.com/) | **GAP** — No supported public feed discovered (no supported feed found on the official careers page) | HTTP 200 |
| 13 | Dell Technologies | [https://jobs.dell.com/](https://jobs.dell.com/) | **VALIDATED** — Oracle HCM: 65 listings | HTTP 200; ATS marker: oraclehcm |
| 14 | JPMorgan Chase | [https://careers.jpmorgan.com/](https://careers.jpmorgan.com/) | **VALIDATED** — Oracle HCM: 117 listings | HTTP 200; ATS marker: oraclehcm |
| 15 | Wells Fargo | [https://www.wellsfargojobs.com/](https://www.wellsfargojobs.com/) | **GAP** — No supported public feed discovered (no supported feed found on the official careers page) | HTTP 403 |
| 16 | Adobe | [https://careers.adobe.com/](https://careers.adobe.com/) | **GAP** — No supported public feed discovered (no supported feed found on the official careers page) | HTTP 200; ATS marker: phenom |
| 17 | Intuit | [https://www.intuit.com/in/careers/software-engineering/](https://www.intuit.com/in/careers/software-engineering/) | **GAP** — No matching public job-card pattern found (connector needed) (ValueError x1) | HTTP 200 |
| 18 | Nutanix | [https://careers.nutanix.com/en/locations/india/](https://careers.nutanix.com/en/locations/india/) | **VALIDATED** — Official career page: 5 listings | HTTP 403 |
| 19 | Autodesk | [https://www.autodesk.com/careers](https://www.autodesk.com/careers) | **GAP** — No matching public job-card pattern found (connector needed) (ValueError x1) | HTTP 200 |
| 20 | NetApp | [https://www.netapp.com/company/careers/](https://www.netapp.com/company/careers/) | **VALIDATED** — Eightfold: 21 listings | HTTP 200; ATS marker: eightfold, successfactors |
| 21 | Commvault | [https://www.commvault.com/careers](https://www.commvault.com/careers) | **VALIDATED** — Greenhouse API: 52 listings (rechecked after full run) | HTTP 200 |
| 22 | Informatica | [https://www.informatica.com/careers.html](https://www.informatica.com/careers.html) | **GAP** — No supported public feed discovered (no supported feed found on the official careers page) | HTTP 200 |
| 23 | Teradata | [https://careers.teradata.com/](https://careers.teradata.com/) | **GAP** — No supported public feed discovered (no supported feed found on the official careers page) | HTTP 200 |
| 24 | ADP | [https://jobs.adp.com/](https://jobs.adp.com/) | **GAP** — No supported public feed discovered (no supported feed found on the official careers page) | HTTP 403 |
| 25 | Qualcomm | [https://careers.qualcomm.com/](https://careers.qualcomm.com/) | **GAP** — Eightfold candidate returned no usable listings in the full run | HTTP 200; ATS marker: eightfold |
| 26 | NVIDIA | [https://www.nvidia.com/en-us/about-nvidia/careers/](https://www.nvidia.com/en-us/about-nvidia/careers/) | **GAP** — No matching public job-card pattern found (connector needed) (ValueError x1) | HTTP 200 |
| 27 | AMD | [https://careers.amd.com/](https://careers.amd.com/) | **GAP** — No supported public feed discovered (no supported feed found on the official careers page) | HTTP 200; ATS marker: icims |
| 28 | Siemens | [https://www.siemens.com/careers](https://www.siemens.com/careers) | **GAP** — Official career page candidate returned no usable listings in the full run | HTTP 200 |
| 29 | Goldman Sachs | [https://higher.gs.com/](https://higher.gs.com/) | **GAP** — No matching public job-card pattern found (connector needed) (ValueError x1) | HTTP 200 |
| 30 | Flipkart | [https://www.flipkartcareers.com/](https://www.flipkartcareers.com/) | **GAP** — No matching public job-card pattern found (connector needed) (ValueError x1) | HTTP 200 |
| 31 | Oracle — other engineering teams | [https://careers.oracle.com/](https://careers.oracle.com/) | **VALIDATED** — Oracle HCM: 115 listings | HTTP 200; ATS marker: oraclehcm |
| 32 | Temenos | [https://www.temenos.com/careers/](https://www.temenos.com/careers/) | **VALIDATED** — Workday: 18 listings | HTTP 200; ATS marker: workday |
| 33 | Finastra | [https://www.finastra.com/careers](https://www.finastra.com/careers) | **VALIDATED** — Workday: 20 listings | HTTP 200; ATS marker: workday |
| 34 | FIS | [https://www.fisglobal.com/careers](https://www.fisglobal.com/careers) | **GAP** — No matching public job-card pattern found (connector needed) (ValueError x1) | HTTP 200 |
| 35 | Broadridge | [https://www.broadridge.com/careers](https://www.broadridge.com/careers) | **VALIDATED** — Workday: 20 listings | HTTP 200; ATS marker: workday |
| 36 | Bank of America | [https://careers.bankofamerica.com/](https://careers.bankofamerica.com/) | **VALIDATED** — Workday: 280 listings | HTTP 200; ATS marker: workday |
| 37 | State Street | [https://www.statestreet.com/careers](https://www.statestreet.com/careers) | **VALIDATED** — Workday: 80 listings | HTTP 200; ATS marker: workday, phenom |
| 38 | Capital One | [https://www.capitalonecareers.com/](https://www.capitalonecareers.com/) | **VALIDATED** — Workday: 14 listings | HTTP 200; ATS marker: workday, eightfold |
| 39 | American Express | [https://www.americanexpress.com/en-in/careers/](https://www.americanexpress.com/en-in/careers/) | **GAP** — No supported public feed discovered (no supported feed found on the official careers page) | No response captured |
| 40 | Infosys Finacle | [https://www.infosys.com/careers/](https://www.infosys.com/careers/) | **GAP** — No matching public job-card pattern found (connector needed) (ValueError x1) | HTTP 200 |
| 41 | Honeywell | [https://careers.honeywell.com/](https://careers.honeywell.com/) | **VALIDATED** — Oracle HCM: 79 listings | HTTP 200; ATS marker: oraclehcm, phenom |
| 42 | Synchrony | [https://www.synchronycareers.com/](https://www.synchronycareers.com/) | **VALIDATED** — Official career page: 15 listings (rechecked after full run) | HTTP 200 |
| 43 | HighRadius | [https://www.highradius.com/about/career/](https://www.highradius.com/about/career/) | **VALIDATED** — Greenhouse: 70 listings | HTTP 200; ATS marker: greenhouse |
| 44 | Freshworks | [https://www.freshworks.com/company/careers/](https://www.freshworks.com/company/careers/) | **VALIDATED** — SmartRecruiters: 53 listings | HTTP 200; ATS marker: smartrecruiters |
| 45 | Thoughtworks | [https://www.thoughtworks.com/careers](https://www.thoughtworks.com/careers) | **VALIDATED** — Greenhouse: 43 listings | HTTP 200 |
| 46 | EPAM Systems | [https://www.epam.com/careers](https://www.epam.com/careers) | **GAP** — No supported public feed discovered (no supported feed found on the official careers page) | HTTP 403 |
| 47 | Publicis Sapient | [https://www.publicissapient.com/careers](https://www.publicissapient.com/careers) | **GAP** — Official career page candidate returned no usable listings in the full run | HTTP 200 |
| 48 | Deloitte USI | [https://usijobs.deloitte.com/](https://usijobs.deloitte.com/) | **GAP** — No matching public job-card pattern found (connector needed) (ValueError x1) | HTTP 200 |
| 49 | EY GDS | [https://careers.ey.com/](https://careers.ey.com/) | **VALIDATED** — Official career page: 25 listings | HTTP 200; ATS marker: successfactors |
| 50 | Accenture | [https://www.accenture.com/in-en/careers](https://www.accenture.com/in-en/careers) | **VALIDATED** — Workday: 20 listings | HTTP 200; ATS marker: workday |
| 51 | Samsung R&D (SRI-Bangalore) | [https://research.samsung.com/careers](https://research.samsung.com/careers) | **VALIDATED** — Workday: 20 listings | HTTP 200; ATS marker: workday |
| 52 | Mahindra Comviva | [https://www.comviva.com/careers/](https://www.comviva.com/careers/) | **GAP** — No matching public job-card pattern found (connector needed) (ValueError x1) | HTTP 200 |
| 53 | Ascendion | [https://ascendion.com/careers/](https://ascendion.com/careers/) | **GAP** — No matching public job-card pattern found (connector needed) (ValueError x1) | HTTP 200 |

## Activation checklist

1. Upload the contents of this project to a private GitHub repository, keeping `.github/workflows/watch.yml` in place.
2. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` under repository **Settings → Secrets and variables → Actions**.
3. Optional: add `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` as Actions secrets. Adzuna is a secondary source and may not list every company opening.
4. Run the `selftest` workflow, review all 53 lines, then run `normal` once. The workflow is scheduled every 10 minutes, subject to GitHub scheduling delays.
5. Do not treat the setup as complete for all 53 until the remaining 25 rows return a validated source or are explicitly covered by an enabled fallback.

No LinkedIn source or scraper is used. Sources are direct employer career pages/ATS APIs where validated; company careers links remain in the table for manual recovery when an adapter is unavailable.
