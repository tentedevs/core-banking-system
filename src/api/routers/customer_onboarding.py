from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from auth_client import CurrentActor
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.dependencies import AccountWorkDependency
from api.routers.customer_transfers import transfer_actor
from api.schemas.account import AccountResponse
from application.use_cases.onboard_customer import OnboardCustomer
from infrastructure.crp_customer_provisioner import CRPCustomerProvisioner
from ports.actor_customer_link_repository import ActorAlreadyLinked
from ports.customer_onboarding import (
    CustomerProfileRejected,
    CustomerProvisioningUnavailable,
    OnboardingConflict,
)

NonNegativeMoney = Annotated[
    Decimal, Field(ge=0, allow_inf_nan=False, max_digits=18, decimal_places=2)
]


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    birth_date: date
    employment_status: Literal["EMPLOYED", "SELF_EMPLOYED", "UNEMPLOYED", "RETIRED", "STUDENT"]
    employment_months: int | None = Field(default=None, ge=0)
    monthly_net_income: NonNegativeMoney
    monthly_housing_cost: NonNegativeMoney
    monthly_debt_payments: NonNegativeMoney
    monthly_basic_expenses: NonNegativeMoney
    housing_status: Literal["OWNER", "MORTGAGE", "RENT", "OTHER"]
    country_of_residence: str = Field(pattern="^[A-Z]{2}$")
    currency: str = Field(default="CZK", pattern="^[A-Z]{3}$")

    @field_validator("birth_date")
    @classmethod
    def not_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Birth date cannot be in the future")
        return value

    def customer_profile(self) -> dict[str, object]:
        values: dict[str, object] = self.model_dump(mode="json", exclude={"currency"})
        for name in (
            "monthly_net_income",
            "monthly_housing_cost",
            "monthly_debt_payments",
            "monthly_basic_expenses",
        ):
            values[name] = format(getattr(self, name), ".2f")
        return values


router = APIRouter(prefix="/me", tags=["Customer onboarding"])


@router.post("/onboarding", status_code=201, response_model=AccountResponse)
def onboard(
    payload: OnboardingRequest,
    actor: Annotated[CurrentActor, Depends(transfer_actor)],
    work: AccountWorkDependency,
    request: Request,
    response: Response,
) -> AccountResponse:
    return provision_account(payload, actor, work, request, response)


def provision_account(
    payload: OnboardingRequest,
    actor: CurrentActor,
    work: AccountWorkDependency,
    request: Request,
    response: Response,
) -> AccountResponse:
    settings = request.app.state.settings
    if not settings.crp_customer_service_url or not settings.crp_customer_provisioning_credential:
        raise HTTPException(status_code=503, detail="El alta bancaria no está configurada.")
    try:
        with CRPCustomerProvisioner(
            settings.crp_customer_service_url,
            settings.crp_customer_provisioning_credential.get_secret_value(),
            allow_insecure_http=settings.crp_customer_allow_insecure_http,
            timeout=settings.crp_customer_request_timeout,
        ) as customers:
            account = OnboardCustomer(work, customers).execute(
                actor, payload.customer_profile(), payload.currency
            )
    except CustomerProfileRejected:
        raise HTTPException(
            status_code=422, detail="Revisa los datos del perfil bancario."
        ) from None
    except (OnboardingConflict, ActorAlreadyLinked):
        raise HTTPException(
            status_code=409,
            detail=(
                "El alta ya existe o requiere los datos originales. "
                "Actualiza la sesión o contacta con el operador."
            ),
        ) from None
    except CustomerProvisioningUnavailable:
        raise HTTPException(
            status_code=503, detail="No se puede confirmar el alta. Reintenta con los mismos datos."
        ) from None
    response.headers["Cache-Control"] = "no-store"
    return AccountResponse.model_validate(account)
