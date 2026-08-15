/* ThinkBallot mock dataset — ENTIRELY FICTIONAL placeholder data.
   Framed as the Nov 3, 2026 California general election, but every proposition,
   measure, candidate, argument, and number below is invented for the mock. */

const TB = {
  election: {
    id: "2026-11-03-ca-general",
    name: "November 3, 2026 California General Election",
    date: "2026-11-03",
  },

  addresses: {
    cupertino: {
      label: "1 Infinite Loop, Cupertino, CA 95014",
      county: "Santa Clara County",
      districts: { cd: "CD-17", sd: "SD-13", ad: "AD-24" },
      coverage: "full",
    },
    eureka: {
      label: "742 Evergreen Terrace, Eureka, CA 95501",
      county: "Humboldt County",
      districts: { cd: "CD-02", sd: "SD-02", ad: "AD-02" },
      coverage: "low",
    },
  },

  sources: {
    "src-sos": { label: "CA Secretary of State — Official Voter Information Guide (mock)", url: "#src-sos" },
    "src-lao": { label: "Legislative Analyst's Office — Fiscal Analysis (mock)", url: "#src-lao" },
    "src-scc": { label: "Santa Clara County Registrar of Voters (mock)", url: "#src-scc" },
    "src-bp": { label: "Ballotpedia (mock)", url: "#src-bp" },
    "src-cand": { label: "Official candidate statements (mock)", url: "#src-cand" },
  },

  measures: [
    {
      id: "prop-61",
      type: "measure",
      scope: "Statewide",
      title: "Proposition 61: Community College Facilities Bond",
      summary:
        "Authorizes $8 billion in state bonds to repair and build community college classrooms, labs, and student housing. Repaid from the state's general fund over about 30 years.",
      yes: "The state may borrow $8 billion for community college construction and repairs, repaid with interest from existing state revenues.",
      no: "The state may not issue these bonds; community college facility projects would rely on existing local and state funding.",
      argsFor: [
        { text: "Many campuses have buildings over 50 years old that need seismic and safety upgrades.", src: "src-sos" },
        { text: "Student housing shortages push costs onto low-income students.", src: "src-sos" },
      ],
      argsAgainst: [
        { text: "Bond debt costs roughly $1.60 for every $1 borrowed after interest.", src: "src-sos" },
        { text: "Facility spending should be prioritized within the existing budget.", src: "src-sos" },
      ],
      fiscal: { text: "Estimated state cost of about $460 million per year for 30 years to repay the bond.", src: "src-lao" },
      topics: ["education", "bonds"],
      civicFeatures: ["bond"],
      sponsors: ["State Legislature (placed on ballot)"],
      sources: ["src-sos", "src-lao"],
    },
    {
      id: "prop-62",
      type: "measure",
      scope: "Statewide",
      title: "Proposition 62: Water Infrastructure and Drought Resilience Act",
      summary:
        "Dedicates 1.5% of the state general fund annually for ten years to water storage, recycling, and groundwater recharge projects, with independent audits.",
      yes: "About $3 billion per year would be set aside for water projects for ten years, reducing funds available for other programs.",
      no: "Water project funding would continue to be decided year-by-year in the state budget.",
      argsFor: [
        { text: "Guarantees stable, long-term investment in water security regardless of budget cycles.", src: "src-sos" },
        { text: "Independent audit board reviews every funded project annually.", src: "src-sos" },
      ],
      argsAgainst: [
        { text: "Locks up general-fund money that may be needed for schools or health in lean years.", src: "src-sos" },
        { text: "Existing water bonds remain only partially spent.", src: "src-sos" },
      ],
      fiscal: { text: "Redirects roughly $3 billion annually for ten years; long-term savings from drought mitigation are uncertain.", src: "src-lao" },
      topics: ["water", "environment", "budget"],
      civicFeatures: ["appropriation"],
      sponsors: ["Citizens' initiative — Water Security Now Coalition (fictional)"],
      sources: ["src-sos", "src-lao"],
    },
    {
      id: "prop-63",
      type: "measure",
      scope: "Statewide",
      title: "Proposition 63: Rental Housing Tax Adjustment",
      summary:
        "Changes how multi-unit rental properties are reassessed for property taxes, moving from sale-triggered reassessment to a three-year cycle for buildings with 10+ units.",
      yes: "Large rental properties would be reassessed every three years, generally increasing property tax revenue for local governments.",
      no: "Rental properties would continue to be reassessed only when sold, as under current law.",
      argsFor: [
        { text: "Long-held rental portfolios pay taxes on decades-old valuations while renters bear rising costs.", src: "src-sos" },
        { text: "New revenue is directed to county affordable-housing funds.", src: "src-sos" },
      ],
      argsAgainst: [
        { text: "Higher taxes on landlords are likely to be passed through to renters.", src: "src-sos" },
        { text: "Adds assessment workload and disputes for county assessors.", src: "src-sos" },
      ],
      fiscal: { text: "Increased local property tax revenue of $2–4 billion annually once fully phased in, offset by administration costs.", src: "src-lao" },
      topics: ["housing", "taxes"],
      civicFeatures: ["tax"],
      sponsors: ["Citizens' initiative — Fair Assessment Project (fictional)"],
      sources: ["src-sos", "src-lao"],
    },
    {
      id: "prop-64",
      type: "measure",
      scope: "Statewide",
      title: "Proposition 64: AI Systems in Public Agencies Transparency Act",
      summary:
        "Requires state and local agencies to publicly disclose automated decision systems used in benefits, policing, and hiring, and to provide a human-review appeal path.",
      yes: "Agencies must publish registries of automated decision systems and offer human review of automated decisions.",
      no: "No statewide disclosure requirement; agencies set their own policies on automated systems.",
      argsFor: [
        { text: "Residents deserve to know when an algorithm, not a person, decides their case.", src: "src-sos" },
        { text: "Human-review appeals catch automation errors before they cause harm.", src: "src-sos" },
      ],
      argsAgainst: [
        { text: "Compliance costs divert agency budgets from services.", src: "src-sos" },
        { text: "Broad definitions could cover routine software and create legal uncertainty.", src: "src-sos" },
      ],
      fiscal: { text: "Tens of millions of dollars annually in state and local administrative costs, depending on implementation.", src: "src-lao" },
      topics: ["technology", "government"],
      civicFeatures: ["statute"],
      sponsors: ["State Legislature (placed on ballot)"],
      sources: ["src-sos", "src-lao"],
    },
  ],

  races: [
    {
      id: "us-house-17",
      type: "race",
      scope: "CD-17",
      office: "U.S. House of Representatives — District 17",
      summaryNote: "Every candidate receives the same fields, length budget, and neutral tone, drawn from official statements.",
      candidates: [
        { name: "Maya Delgado", party: "Democratic", summary: "County supervisor; campaign priorities listed as housing affordability, transit expansion, and semiconductor workforce programs.", src: "src-cand" },
        { name: "Robert Kwan", party: "Republican", summary: "Small-business owner; campaign priorities listed as small-business tax relief, public-safety funding, and permitting reform.", src: "src-cand" },
      ],
      topics: ["federal"],
      civicFeatures: ["office"],
      sources: ["src-cand", "src-bp"],
    },
    {
      id: "state-senate-13",
      type: "race",
      scope: "SD-13",
      office: "State Senate — District 13",
      summaryNote: "Every candidate receives the same fields, length budget, and neutral tone, drawn from official statements.",
      candidates: [
        { name: "Priya Raman", party: "Democratic", summary: "City councilmember; campaign priorities listed as school funding, wildfire insurance reform, and caltrain electrification.", src: "src-cand" },
        { name: "Dale Whitfield", party: "Republican", summary: "Retired fire captain; campaign priorities listed as emergency preparedness, budget oversight, and housing streamlining.", src: "src-cand" },
      ],
      topics: ["state"],
      civicFeatures: ["office"],
      sources: ["src-cand", "src-bp"],
    },
    {
      id: "state-assembly-24",
      type: "race",
      scope: "AD-24",
      office: "State Assembly — District 24",
      summaryNote: "Every candidate receives the same fields, length budget, and neutral tone, drawn from official statements.",
      candidates: [
        { name: "Grace Okafor", party: "Democratic", summary: "Nonprofit director; campaign priorities listed as childcare access, renter protections, and community college funding.", src: "src-cand" },
        { name: "Tom Alvarez", party: "Libertarian", summary: "Software engineer; campaign priorities listed as occupational-licensing reform, budget transparency, and privacy law.", src: "src-cand" },
      ],
      topics: ["state"],
      civicFeatures: ["office"],
      sources: ["src-cand", "src-bp"],
    },
  ],

  countyMeasures: [
    {
      id: "scc-measure-a",
      type: "measure",
      scope: "Santa Clara County",
      title: "Measure A: Transit Connectivity Sales Tax",
      summary:
        "A ⅜-cent county sales tax for 20 years to fund light-rail extensions, bus rapid transit, and bicycle infrastructure, with citizen oversight.",
      yes: "The county sales tax rises by ⅜ cent for 20 years, funding the listed transit projects.",
      no: "The sales tax stays the same; the transit projects would need other funding.",
      argsFor: [
        { text: "Traffic congestion costs county commuters an estimated 62 hours per year.", src: "src-scc" },
        { text: "Independent oversight committee audits all expenditures annually.", src: "src-scc" },
      ],
      argsAgainst: [
        { text: "Sales taxes fall hardest on lower-income households.", src: "src-scc" },
        { text: "Prior transit measures have seen delayed project delivery.", src: "src-scc" },
      ],
      fiscal: { text: "Raises approximately $6.2 billion over 20 years for county transit projects.", src: "src-scc" },
      topics: ["transit", "taxes"],
      civicFeatures: ["tax"],
      sponsors: ["Santa Clara County Board of Supervisors (fictional placement)"],
      sources: ["src-scc"],
    },
    {
      id: "scc-measure-b",
      type: "measure",
      scope: "Santa Clara County",
      title: "Measure B: Library Parcel Tax Renewal",
      summary:
        "Renews an existing $48 annual parcel tax for 12 years to maintain library hours, youth literacy programs, and branch maintenance.",
      yes: "The existing $48 parcel tax continues for 12 more years, maintaining current library funding.",
      no: "The parcel tax expires in 2027; library funding would be reduced or found elsewhere.",
      argsFor: [
        { text: "Renewal maintains current service levels without raising the rate.", src: "src-scc" },
        { text: "Senior and low-income exemptions continue unchanged.", src: "src-scc" },
      ],
      argsAgainst: [
        { text: "Parcel taxes apply equally to small homes and large commercial parcels.", src: "src-scc" },
        { text: "Library services should compete within the county general fund.", src: "src-scc" },
      ],
      fiscal: { text: "Continues roughly $21 million per year in dedicated library funding.", src: "src-scc" },
      topics: ["libraries", "taxes"],
      civicFeatures: ["tax", "renewal"],
      sponsors: ["Santa Clara County Board of Supervisors (fictional placement)"],
      sources: ["src-scc"],
    },
  ],

  comments: {
    "prop-61": [
      { who: "juniper_sf · 2d ago", text: "The housing piece is what sold me — my sister lives 90 minutes from her campus because there's nothing affordable nearby." },
      { who: "fiscal_hawk_99 · 1d ago", text: "Everyone forgets bonds are loans. Read the LAO number: $460M a year is a whole program's worth of money." },
    ],
    "prop-62": [
      { who: "delta_farmer · 3d ago", text: "Ask anyone in the valley what an empty reservoir summer feels like. Stable funding matters." },
    ],
    "scc-measure-a": [
      { who: "vta_rider · 5h ago", text: "BRT on El Camino would change my commute completely. The oversight committee history is worth reading though." },
    ],
  },

  communityFacts: {
    "prop-61": [
      {
        status: "vetted",
        text: "The 2016 community college bond (fictional Prop 51 analog) has disbursed 84% of funds as of 2025, per the state treasurer's report.",
        meta: "submitted by cc_trustee · 2 citations · rated helpful across perspectives · reviewed",
      },
      {
        status: "pending",
        text: "Three campuses in the Central Valley have buildings red-tagged for seismic risk.",
        meta: "submitted by seismic_eng · 1 citation · awaiting cross-perspective ratings",
      },
    ],
    "prop-62": [
      {
        status: "rejected",
        text: "This proposition will end agricultural water use in the state.",
        meta: "submitted anonymously · no citation provided → failed grounding check (cite-or-omit)",
      },
    ],
  },

  qa: [
    {
      q: "What happens to my property taxes if Prop 63 passes?",
      a: "If you own a rental building with 10 or more units, it would be reassessed every three years instead of only at sale, which generally increases its property tax. Single-family homes and smaller properties are not affected by the measure as written.",
      cites: ["src-sos", "src-lao"],
    },
    {
      q: "How much does Prop 61 cost the state?",
      a: "The Legislative Analyst's Office estimates repayment costs of about $460 million per year for roughly 30 years, paid from the state general fund.",
      cites: ["src-lao"],
    },
    {
      q: "Who is on my ballot for U.S. House?",
      a: "For the sample Cupertino address (District 17), two candidates are on the mock ballot: Maya Delgado (Democratic) and Robert Kwan (Republican). Each has an equal, sourced summary on the race card.",
      cites: ["src-cand"],
    },
  ],
  qaRefusal:
    "I can't answer that from the grounded ballot dataset for this election, so I won't guess. I only answer with information that carries a citation — try asking about a measure or race on your ballot.",
};

/* Ballot composition per sample address */
TB.ballotFor = function (addrKey) {
  const a = TB.addresses[addrKey] || TB.addresses.cupertino;
  const races =
    addrKey === "eureka"
      ? [] // mock: race cards not composed for the low-coverage demo address
      : TB.races;
  const county = a.coverage === "full" ? TB.countyMeasures : [];
  return { address: a, measures: TB.measures, races, county };
};

TB.findItem = function (id) {
  return (
    TB.measures.find((m) => m.id === id) ||
    TB.countyMeasures.find((m) => m.id === id) ||
    TB.races.find((r) => r.id === id) ||
    null
  );
};

TB.allItems = function () {
  return [...TB.measures, ...TB.countyMeasures, ...TB.races];
};
