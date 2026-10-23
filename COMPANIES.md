# All 105 companies - source, evidence and status

**Honest status:** I cannot reach any of these sites from my environment, so nothing below is live-tested by me. 'Evidence' is what your own 19-Oct self-test showed.
For the 52 added companies the hints (Greenhouse / Lever / Ashby / Workday names) come from my memory and are verified by the bot before use - wrong guesses are harmless.
The self-test prints, per company: route, jobs read, pagination status and last successful retrieval (stored in `state/db.json`).
LinkedIn and Indeed are not used. 'Acolite' and 'Accolite / Bounteous' are the same company and appear once; 'Lowis' was read as Lowe's - tell me if you meant someone else.

| # | Company | Careers page | Configured route | Evidence | Status |
|---|---|---|---|---|---|
| 1 | Salesforce | https://careers.salesforce.com/en/jobs/?country=India | hint: workday | FAILED in your 19-Oct log: rate-limit cooldown (HTTP 429) | NOT working yet - new resolver / route added, UNTESTED |
| 2 | ServiceNow | https://careers.servicenow.com/locations/apj/india/ | hint: html_listing | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 3 | Cisco | https://careers.cisco.com/global/en/india/ | auto-discovery ladder | READ OK in your 19-Oct log (95 jobs read) | working (user-reported) |
| 4 | Visa | https://corporate.visa.com/en/jobs | auto-discovery ladder | READ OK in your 19-Oct log (86 jobs read) | working (user-reported) |
| 5 | Mastercard | https://careers.mastercard.com/ | hint: workday | READ OK in your 19-Oct log (82 jobs read) | working (user-reported) |
| 6 | PayPal | https://www.paypal.com/us/webapps/mpp/jobs | hint: eightfold | feed answered with 0 jobs | NOT working yet - new resolver / route added, UNTESTED |
| 7 | SAP | https://careers.sap.com/go/India/8807201/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 8 | Pegasystems | https://www.pega.com/about/careers | hint: workday | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 9 | Thomson Reuters | https://www.thomsonreuters.com/en/careers.html | hint: workday | READ OK in your 19-Oct log (86 jobs read) | working (user-reported) |
| 10 | Target | https://corporate.target.com/careers | hint: workday | READ OK in your 19-Oct log (66 jobs read) | working (user-reported) |
| 11 | Experian | https://jobs.experian.com/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 12 | Walmart Global Tech | https://careers.walmart.com/ | hint: workday | FAILED in your 19-Oct log: HTTP 422 x10 | NOT working yet - new resolver / route added, UNTESTED |
| 13 | Dell Technologies | https://jobs.dell.com/ | hint: workday | FAILED in your 19-Oct log: HTTP 422 x10 | NOT working yet - new resolver / route added, UNTESTED |
| 14 | JPMorgan Chase | https://careers.jpmorgan.com/ | hint: oraclehcm | READ OK in your 19-Oct log (123 jobs read) | working (user-reported) |
| 15 | Wells Fargo | https://www.wellsfargojobs.com/ | hint: workday | FAILED in your 19-Oct log: HTTP 422 x10 | NOT working yet - new resolver / route added, UNTESTED |
| 16 | Adobe | https://careers.adobe.com/ | hint: workday | READ OK in your 19-Oct log (65 jobs read) | working (user-reported) |
| 17 | Intuit | https://www.intuit.com/in/careers/software-engineering/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 18 | Nutanix | https://careers.nutanix.com/en/locations/india/ | hint: workday | FAILED in your 19-Oct log: HTTP 422 x24, HTTP 401 x6 | NOT working yet - new resolver / route added, UNTESTED |
| 19 | Autodesk | https://www.autodesk.com/careers | hint: workday | READ OK in your 19-Oct log (63 jobs read) | working (user-reported) |
| 20 | NetApp | https://www.netapp.com/company/careers/ | hint: workday | FAILED in your 19-Oct log: HTTP 422 x10 | NOT working yet - new resolver / route added, UNTESTED |
| 21 | Commvault | https://www.commvault.com/careers | hint: workday | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 22 | Informatica | https://www.informatica.com/careers.html | hint: workday | FAILED in your 19-Oct log: HTTP 422 x8, HTTP 401 x2 | NOT working yet - new resolver / route added, UNTESTED |
| 23 | Teradata | https://careers.teradata.com/ | hint: workday | FAILED in your 19-Oct log: HTTP 422 x16, HTTP 401 x4 | NOT working yet - new resolver / route added, UNTESTED |
| 24 | ADP | https://jobs.adp.com/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 25 | Qualcomm | https://careers.qualcomm.com/ | hint: workday | feed answered with 0 jobs | NOT working yet - new resolver / route added, UNTESTED |
| 26 | NVIDIA | https://www.nvidia.com/en-us/about-nvidia/careers/ | hint: workday | READ OK in your 19-Oct log (114 jobs read) | working (user-reported) |
| 27 | AMD | https://careers.amd.com/ | hint: workday | FAILED in your 19-Oct log: HTTP 422 x10 | NOT working yet - new resolver / route added, UNTESTED |
| 28 | Siemens | https://www.siemens.com/careers | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 29 | Goldman Sachs | https://higher.gs.com/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 30 | Flipkart | https://www.flipkartcareers.com/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 31 | Oracle — other engineering teams | https://careers.oracle.com/ | hint: oraclehcm | READ OK in your 19-Oct log (114 jobs read) | working (user-reported) |
| 32 | Temenos | https://www.temenos.com/careers/ | auto-discovery ladder | READ OK in your 19-Oct log (1 jobs read) | working (user-reported) |
| 33 | Finastra | https://www.finastra.com/careers | auto-discovery ladder | READ OK in your 19-Oct log (49 jobs read) | working (user-reported) |
| 34 | FIS | https://www.fisglobal.com/careers | hint: workday | READ OK in your 19-Oct log (68 jobs read) | working (user-reported) |
| 35 | Broadridge | https://www.broadridge.com/careers | hint: workday | READ OK in your 19-Oct log (57 jobs read) | working (user-reported) |
| 36 | Bank of America | https://careers.bankofamerica.com/ | auto-discovery ladder | READ OK in your 19-Oct log (64 jobs read) | working (user-reported) |
| 37 | State Street | https://www.statestreet.com/careers | hint: workday | READ OK in your 19-Oct log (95 jobs read) | working (user-reported) |
| 38 | Capital One | https://www.capitalonecareers.com/ | hint: workday | READ OK in your 19-Oct log (93 jobs read) | working (user-reported) |
| 39 | American Express | https://www.americanexpress.com/en-in/careers/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 40 | Infosys Finacle | https://www.infosys.com/careers/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 41 | Honeywell | https://careers.honeywell.com/ | hint: workday | FAILED in your 19-Oct log: HTTP 422 x10 | NOT working yet - new resolver / route added, UNTESTED |
| 42 | Synchrony | https://www.synchronycareers.com/ | hint: workday | READ OK in your 19-Oct log (4 jobs read) | working (user-reported) |
| 43 | HighRadius | https://www.highradius.com/about/career/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 44 | Freshworks | https://www.freshworks.com/company/careers/ | auto-discovery ladder | READ OK in your 19-Oct log (88 jobs read) | working (user-reported) |
| 45 | Thoughtworks | https://www.thoughtworks.com/careers | hint: greenhouse | READ OK in your 19-Oct log (43 jobs read) | working (user-reported) |
| 46 | EPAM Systems | https://www.epam.com/careers | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 47 | Publicis Sapient | https://www.publicissapient.com/careers | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 48 | Deloitte USI | https://usijobs.deloitte.com/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 49 | EY GDS | https://careers.ey.com/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 50 | Accenture | https://www.accenture.com/in-en/careers | auto-discovery ladder | READ OK in your 19-Oct log (117 jobs read) | working (user-reported) |
| 51 | Samsung R&D (SRI-Bangalore) | https://research.samsung.com/careers | auto-discovery ladder | READ OK in your 19-Oct log (46 jobs read) | working (user-reported) |
| 52 | Mahindra Comviva | https://www.comviva.com/careers/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 53 | Ascendion | https://ascendion.com/careers/ | auto-discovery ladder | 'no job feed found' in your 19-Oct log | NOT working yet - new resolver / route added, UNTESTED |
| 54 | Barclays | https://search.jobs.barclays/ | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 55 | Microsoft | https://jobs.careers.microsoft.com/global/en/search?lc=India | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 56 | Google | https://www.google.com/about/careers/applications/jobs/results?location=India | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 57 | Atlassian | https://www.atlassian.com/company/careers/all-jobs | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 58 | Razorpay | https://razorpay.com/jobs/ | hint: greenhouse | never tested | UNTESTED - route guessed from my knowledge |
| 59 | Zeta | https://www.zeta.tech/in/careers/ | hint: greenhouse/lever | never tested | UNTESTED - route guessed from my knowledge |
| 60 | Zoho | https://www.zoho.com/careers/ | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 61 | DE Shaw | https://www.deshawindia.com/careers | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 62 | Snowflake | https://careers.snowflake.com/ | hint: greenhouse/workday | never tested | UNTESTED - route guessed from my knowledge |
| 63 | Expedia Group | https://careers.expediagroup.com/ | hint: workday | never tested | UNTESTED - route guessed from my knowledge |
| 64 | eBay | https://jobs.ebayinc.com/ | hint: workday | never tested | UNTESTED - route guessed from my knowledge |
| 65 | Airbnb | https://careers.airbnb.com/ | hint: greenhouse | never tested | UNTESTED - route guessed from my knowledge |
| 66 | Morgan Stanley | https://www.morganstanley.com/careers | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 67 | Deloitte Global | https://www.deloitte.com/global/en/careers.html | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 68 | Sprinklr | https://www.sprinklr.com/careers/ | hint: greenhouse/lever | never tested | UNTESTED - route guessed from my knowledge |
| 69 | Agoda | https://careersatagoda.com/ | hint: greenhouse/lever | never tested | UNTESTED - route guessed from my knowledge |
| 70 | Meesho | https://careers.meesho.com/ | hint: greenhouse/lever | never tested | UNTESTED - route guessed from my knowledge |
| 71 | Rubrik | https://www.rubrik.com/company/careers | hint: greenhouse | never tested | UNTESTED - route guessed from my knowledge |
| 72 | Media.net | https://www.media.net/careers | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 73 | Databricks | https://www.databricks.com/company/careers | hint: greenhouse | never tested | UNTESTED - route guessed from my knowledge |
| 74 | Zomato | https://www.zomato.com/careers | hint: greenhouse/lever | never tested | UNTESTED - route guessed from my knowledge |
| 75 | Rippling | https://www.rippling.com/careers | hint: ashby | never tested | UNTESTED - route guessed from my knowledge |
| 76 | Paytm | https://paytm.com/careers | hint: greenhouse/lever | never tested | UNTESTED - route guessed from my knowledge |
| 77 | Ola Cabs | https://www.olacabs.com/careers | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 78 | Dropbox | https://jobs.dropbox.com/ | hint: greenhouse | never tested | UNTESTED - route guessed from my knowledge |
| 79 | Intel | https://jobs.intel.com/ | hint: workday | never tested | UNTESTED - route guessed from my knowledge |
| 80 | Juspay | https://juspay.io/careers | hint: greenhouse/lever | never tested | UNTESTED - route guessed from my knowledge |
| 81 | Myntra | https://careers.myntra.com/ | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 82 | Accolite / Bounteous | https://www.bounteous.com/careers | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 83 | MakeMyTrip | https://careers.makemytrip.com/ | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 84 | HCLTech | https://www.hcltech.com/careers | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 85 | Okta | https://www.okta.com/company/careers/ | hint: greenhouse | never tested | UNTESTED - route guessed from my knowledge |
| 86 | Booking.com | https://jobs.booking.com/ | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 87 | HP | https://jobs.hp.com/ | hint: workday | never tested | UNTESTED - route guessed from my knowledge |
| 88 | Stripe | https://stripe.com/jobs | hint: greenhouse | never tested | UNTESTED - route guessed from my knowledge |
| 89 | InMobi | https://www.inmobi.com/company/careers | hint: greenhouse | never tested | UNTESTED - route guessed from my knowledge |
| 90 | CrowdStrike | https://www.crowdstrike.com/careers/ | hint: workday | never tested | UNTESTED - route guessed from my knowledge |
| 91 | Nokia | https://www.nokia.com/about-us/careers/ | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 92 | VMware (Broadcom) | https://www.broadcom.com/company/careers | hint: workday | never tested | UNTESTED - route guessed from my knowledge |
| 93 | Groww | https://groww.in/p/careers | hint: greenhouse/lever | never tested | UNTESTED - route guessed from my knowledge |
| 94 | Urban Company | https://www.urbancompany.com/careers | hint: greenhouse/lever | never tested | UNTESTED - route guessed from my knowledge |
| 95 | Optum | https://careers.unitedhealthgroup.com/ | hint: workday | never tested | UNTESTED - route guessed from my knowledge |
| 96 | Virtusa | https://www.virtusa.com/careers | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 97 | HSBC | https://www.hsbc.com/careers | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 98 | Reddit | https://www.redditinc.com/careers | hint: greenhouse | never tested | UNTESTED - route guessed from my knowledge |
| 99 | Shopify | https://www.shopify.com/careers | hint: ashby | never tested | UNTESTED - route guessed from my knowledge |
| 100 | Airbus | https://www.airbus.com/en/careers | hint: workday | never tested | UNTESTED - route guessed from my knowledge |
| 101 | PwC | https://www.pwc.in/careers.html | hint: workday | never tested | UNTESTED - route guessed from my knowledge |
| 102 | Wissen Technology Services | https://www.wissen.com/careers | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 103 | DrawinBox | https://drawinbox.com/careers | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |
| 104 | Lowe's (you wrote 'Lowis') | https://talent.lowes.com/in/en | hint: workday | never tested | UNTESTED - route guessed from my knowledge |
| 105 | Mahindra Group | https://www.mahindra.com/careers | auto-discovery ladder | never tested | UNTESTED - must be discovered by the bot |

Summary: 22 working per your log - 31 of your first 53 still unproven - 31 added with a guessed ATS route - 21 added with discovery only.
