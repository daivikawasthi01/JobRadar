"""Tests for src/filters.py covering all 24 required test cases from BUILD_SPEC.md §B8.5."""
import pytest
from src.config import FilterConfig
from src.filters import evaluate
from src.models import Job


@pytest.fixture
def cfg():
    return FilterConfig()


def make_test_job(title: str, description: str, location: str) -> Job:
    return Job(
        job_id="test:dummy:1",
        company_key="test:dummy",
        company="DummyCorp",
        ats="test",
        title=title,
        location=location,
        url="https://example.com/job/1",
        description=description,
        posted_at="2026-10-12T00:00:00Z",
        salary=None,
        remote=None,
    )


def test_case_01(cfg):
    """1: Associate Software Engineer | "" | Bengaluru, India -> matched; min_exp 0; signal title_entry"""
    job = make_test_job("Associate Software Engineer", "", "Bengaluru, India")
    res = evaluate(job, cfg)
    assert res.matched is True
    assert res.min_exp == 0.0
    assert res.exp_signal == "title_entry"


def test_case_02(cfg):
    """2: Senior Software Engineer | "3 years experience" | Pune, India -> rejected title_excluded"""
    job = make_test_job("Senior Software Engineer", "3 years experience", "Pune, India")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "title_excluded"


def test_case_03(cfg):
    """3: Software Engineer | "0-2 years of experience" | Hyderabad, India -> matched; min 0; max 2; signal range"""
    job = make_test_job("Software Engineer", "0-2 years of experience", "Hyderabad, India")
    res = evaluate(job, cfg)
    assert res.matched is True
    assert res.min_exp == 0.0
    assert res.max_exp == 2.0
    assert res.exp_signal == "range"


def test_case_04(cfg):
    """4: Software Engineer | "3-5 years of experience" | Mumbai, India -> rejected experience_too_high"""
    job = make_test_job("Software Engineer", "3-5 years of experience", "Mumbai, India")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "experience_too_high"


def test_experience_range_with_en_dash_and_plus(cfg):
    job = make_test_job("Software Engineer", "Experience: 3 – 5 + Years", "Mumbai, India")
    res = evaluate(job, cfg)
    assert res.min_exp == 3.0
    assert res.max_exp == 5.0
    assert res.exp_signal == "range"
    assert res.reject_reason == "experience_too_high"


def test_minimum_relevant_professional_experience(cfg):
    job = make_test_job(
        "Software Engineer",
        "- Minimum 4 years of relevant professional experience in a similar role.",
        "Bengaluru, India",
    )
    res = evaluate(job, cfg)
    assert res.min_exp == 4.0
    assert res.max_exp is None
    assert res.exp_signal == "at_least"
    assert res.reject_reason == "experience_too_high"


@pytest.mark.parametrize(
    ("description", "expected_min", "expected_signal"),
    [
        ("3 yrs exp", 3.0, "plain"),
        ("5 years' experience", 5.0, "plain"),
        ("4 years or more", 4.0, "at_least"),
        ("Minimum 4 years of relevant professional experience", 4.0, "at_least"),
    ],
)
def test_experience_prose_variants(cfg, description, expected_min, expected_signal):
    from src.filters import parse_experience

    min_exp, _, signal = parse_experience("Software Engineer", description)
    assert min_exp == expected_min
    assert signal == expected_signal


def test_case_05(cfg):
    """5: Backend Engineer | "2+ years of experience in Python" | Chennai, India -> matched; min 2"""
    job = make_test_job("Backend Engineer", "2+ years of experience in Python", "Chennai, India")
    res = evaluate(job, cfg)
    assert res.matched is True
    assert res.min_exp == 2.0


def test_case_06(cfg):
    """6: Backend Engineer | "3+ years of experience" | Noida, India -> rejected experience_too_high"""
    job = make_test_job("Backend Engineer", "3+ years of experience", "Noida, India")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "experience_too_high"


def test_case_07(cfg):
    """7: Full Stack Developer | "Freshers can apply" | Pune, India -> matched; min 0; signal fresher_keyword"""
    job = make_test_job("Full Stack Developer", "Freshers can apply", "Pune, India")
    res = evaluate(job, cfg)
    assert res.matched is True
    assert res.min_exp == 0.0
    assert res.exp_signal == "fresher_keyword"


def test_case_08(cfg):
    """8: Full Stack Developer | "We build great products." | Pune, India -> matched; min None; signal unknown"""
    job = make_test_job("Full Stack Developer", "We build great products.", "Pune, India")
    res = evaluate(job, cfg)
    assert res.matched is True
    assert res.min_exp is None
    assert res.exp_signal == "unknown"


def test_case_09(cfg):
    """9: AI Engineer | "Minimum 1 year of experience" | Bengaluru, India -> matched; min 1; signal at_least"""
    job = make_test_job("AI Engineer", "Minimum 1 year of experience", "Bengaluru, India")
    res = evaluate(job, cfg)
    assert res.matched is True
    assert res.min_exp == 1.0
    assert res.exp_signal == "at_least"


def test_case_10(cfg):
    """10: Software Engineer II | "" | Bengaluru, India -> rejected title_excluded"""
    job = make_test_job("Software Engineer II", "", "Bengaluru, India")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "title_excluded"


def test_case_11(cfg):
    """11: Associate Product Manager | "" | Bengaluru, India -> rejected title_excluded (contains "manager")"""
    job = make_test_job("Associate Product Manager", "", "Bengaluru, India")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "title_excluded"


def test_case_12(cfg):
    """12: Software Engineer | "0-2 years. Preferred: 5+ years AWS." | Pune, India -> matched; min 0"""
    job = make_test_job("Software Engineer", "0-2 years. Preferred: 5+ years AWS.", "Pune, India")
    res = evaluate(job, cfg)
    assert res.matched is True
    assert res.min_exp == 0.0


def test_case_13(cfg):
    """13: Graduate Engineer Trainee | "" | Chennai, India -> matched; min 0; signal title_entry"""
    job = make_test_job("Graduate Engineer Trainee", "", "Chennai, India")
    res = evaluate(job, cfg)
    assert res.matched is True
    assert res.min_exp == 0.0
    assert res.exp_signal == "title_entry"


def test_case_14(cfg):
    """14: Data Engineer | "Up to 2 years of experience" | Hyderabad, India -> matched; min 0; max 2; signal up_to"""
    job = make_test_job("Data Engineer", "Up to 2 years of experience", "Hyderabad, India")
    res = evaluate(job, cfg)
    assert res.matched is True
    assert res.min_exp == 0.0
    assert res.max_exp == 2.0
    assert res.exp_signal == "up_to"


def test_case_15(cfg):
    """15: Machine Learning Engineer | "5 years of experience required" | Bengaluru, India -> rejected experience_too_high"""
    job = make_test_job("Machine Learning Engineer", "5 years of experience required", "Bengaluru, India")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "experience_too_high"


def test_case_16(cfg):
    """16: Business Development Associate | "" | Mumbai, India -> rejected role_not_included"""
    job = make_test_job("Business Development Associate", "", "Mumbai, India")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "role_not_included"


def test_case_17(cfg):
    """17: Staff Software Engineer | "" | Pune, India -> rejected title_excluded"""
    job = make_test_job("Staff Software Engineer", "", "Pune, India")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "title_excluded"


def test_case_18(cfg):
    """18: SDE-1 | "" | Bengaluru, India -> matched; min 0; signal title_entry"""
    job = make_test_job("SDE-1", "", "Bengaluru, India")
    res = evaluate(job, cfg)
    assert res.matched is True
    assert res.min_exp == 0.0
    assert res.exp_signal == "title_entry"


def test_case_19(cfg):
    """19: SDE-2 | "" | Bengaluru, India -> rejected title_excluded"""
    job = make_test_job("SDE-2", "", "Bengaluru, India")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "title_excluded"


def test_case_20(cfg):
    """20: Software Engineer | "0-2 years" | San Francisco, CA -> rejected country_not_allowed"""
    job = make_test_job("Software Engineer", "0-2 years", "San Francisco, CA")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "country_not_allowed"


def test_case_21(cfg):
    """21: Software Engineer | "0-2 years" | Remote -> rejected country_unknown (default config)"""
    job = make_test_job("Software Engineer", "0-2 years", "Remote")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "country_unknown"


def test_case_22(cfg):
    """22: Software Engineer | "0-2 years" | Remote - India -> matched"""
    job = make_test_job("Software Engineer", "0-2 years", "Remote - India")
    res = evaluate(job, cfg)
    assert res.matched is True


def test_case_23(cfg):
    """23: Software Engineer Intern | "" | Pune, India -> rejected title_excluded (default config)"""
    job = make_test_job("Software Engineer Intern", "", "Pune, India")
    res = evaluate(job, cfg)
    assert res.matched is False
    assert res.reject_reason == "title_excluded"


def test_case_24(cfg):
    """24: Software Engineer | "Our company has 50 years of history." | Pune, India -> matched; min None; signal unknown"""
    job = make_test_job("Software Engineer", "Our company has 50 years of history.", "Pune, India")
    res = evaluate(job, cfg)
    assert res.matched is True
    assert res.min_exp is None
    assert res.exp_signal == "unknown"


def test_grad_year_matching_target_2027():
    cfg_2027 = FilterConfig(
        target_grad_years=[2027],
        allow_unspecified_grad_year=True,
    )

    # 1. Matches when 2027 explicitly mentioned
    job_2027 = make_test_job("Software Engineer", "Eligibility: 2027 batch BTech students.", "Bengaluru, India")
    res1 = evaluate(job_2027, cfg_2027)
    assert res1.matched is True
    assert 2027 in res1.grad_years

    # 2. Rejects when only past batches mentioned
    job_past = make_test_job("Software Engineer", "Eligibility: 2025 and 2026 batch passouts only.", "Bengaluru, India")
    res2 = evaluate(job_past, cfg_2027)
    assert res2.matched is False
    assert res2.reject_reason == "grad_year_mismatch"
    assert res2.grad_years == [2025, 2026]

    # 3. Matches when batch range includes 2027
    job_range = make_test_job("Software Engineer", "Hiring 2026 - 2027 graduates.", "Bengaluru, India")
    res3 = evaluate(job_range, cfg_2027)
    assert res3.matched is True
    assert 2027 in res3.grad_years

    # 4. Matches when no batch is mentioned (allow_unspecified_grad_year=True)
    job_no_mention = make_test_job("Software Engineer", "Requirements: B.Tech in CS with good problem solving.", "Bengaluru, India")
    res4 = evaluate(job_no_mention, cfg_2027)
    assert res4.matched is True
    assert res4.grad_years == []

    # 5. Rejects when no batch mentioned if allow_unspecified_grad_year=False
    cfg_strict = FilterConfig(
        target_grad_years=[2027],
        allow_unspecified_grad_year=False,
    )
    res5 = evaluate(job_no_mention, cfg_strict)
    assert res5.matched is False
    assert res5.reject_reason == "grad_year_unknown"

    job_list = make_test_job(
        "Software Engineer",
        "Eligibility: 2025 and 2026 batch passouts only.",
        "Bengaluru, India",
    )
    res_list = evaluate(job_list, cfg_2027)
    assert res_list.matched is False
    assert res_list.reject_reason == "grad_year_mismatch"
    assert res_list.grad_years == [2025, 2026]

    job_passing_out = make_test_job(
        "Software Engineer",
        "Only candidates passing out in 2027 may apply.",
        "Bengaluru, India",
    )
    assert evaluate(job_passing_out, cfg_2027).grad_years == [2027]

    job_graduating_between = make_test_job(
        "Software Engineer",
        "Candidates graduating between 2026 and 2027 are eligible.",
        "Bengaluru, India",
    )
    assert evaluate(job_graduating_between, cfg_2027).grad_years == [2026, 2027]


def test_internship_matching_for_2027():
    # When intern is excluded from exclusion list (as in config/config.yaml)
    cfg_with_interns = FilterConfig(
        roles_exclude_title=["senior", "lead", "staff", "manager"],
        target_grad_years=[2027],
        allow_unspecified_grad_year=True,
    )

    job_intern = make_test_job(
        "Software Engineer Intern",
        "Looking for final year B.Tech students graduating in 2027.",
        "Bengaluru, India",
    )
    res = evaluate(job_intern, cfg_with_interns)
    assert res.matched is True
    assert res.min_exp == 0.0
    assert res.exp_signal == "title_entry"
    assert 2027 in res.grad_years


def test_runtime_config_matches_user_criteria():
    from src.config import load_config
    cfg = load_config("config/config.yaml")

    assert cfg.filters.target_grad_years == [2027]
    assert cfg.filters.allow_unspecified_grad_year is True
    assert cfg.filters.require_title_any == ["intern", "internship"]
    assert "intern" not in cfg.filters.roles_exclude_title
    assert "India" in cfg.filters.countries

    for title in ("Software Engineer", "SDE-1", "Associate Software Engineer"):
        job = make_test_job(title, "2027 batch BTech students.", "Hyderabad, India")
        res = evaluate(job, cfg.filters)
        assert res.matched is False
        assert res.reject_reason == "title_required_missing"

    job = make_test_job(
        "SDE Intern",
        "Minimum 4 years of relevant professional experience. 2027 batch BTech students.",
        "Hyderabad, India",
    )
    res = evaluate(job, cfg.filters)
    assert res.matched is True
    assert res.min_exp == 0.0
    assert res.exp_signal == "title_entry"
    assert res.grad_years == [2027]

    job_unknown_year = make_test_job(
        "Software Engineer Intern",
        "Looking for enthusiastic problem solvers.",
        "Hyderabad, India",
    )
    unknown_result = evaluate(job_unknown_year, cfg.filters)
    assert unknown_result.matched is True
