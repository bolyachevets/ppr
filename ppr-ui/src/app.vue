<script lang="ts">
import { useStore } from '@/store/store'
import { StatusCodes } from 'http-status-codes'
import { SessionStorageKeys } from 'sbc-common-components/src/util/constants'
import ConnectHeader from '@sbc-connect/nuxt-core-layer-beta/app/components/Connect/Header/index.vue'
import ConnectSystemBanner from '@sbc-connect/nuxt-core-layer-beta/app/components/Connect/SystemBanner.vue'
import ConnectFooter from '@sbc-connect/nuxt-core-layer-beta/app/components/Connect/Footer.vue'

import {
  authPprError, authAssetsError, draftDeleteError, historyRegError, loginError, openDocError, paymentErrorReg,
  paymentErrorSearch, registrationCompleteError, registrationDeleteError, registrationLoadError,
  registrationOpenDraftError, registrationSaveDraftError, searchResultsError, unitNoteFilingError, exemptionSaveError,
  transportPermitFilingError
} from '@/resources/dialogOptions'
import {
  getFees,
  getFeatureFlag,
  getKeycloakRoles,
  getSbcFromAuth,
  updateLdUser,
  axios,
  parsePayDetail
} from '@/utils'
import { getPPRUserSettings  } from '@/utils/ppr-api-helper'
import { FeeCodes } from '@/composables/fees/enums'
import {
  APIRegistrationTypes,
  ErrorCategories,
  ErrorCodes,
  RegistrationFlowType,
  RouteNames,
  ProductCode
} from '@/enums'
import type {
  DialogOptionsIF, ErrorIF, UserInfoIF, UserSettingsIF
} from '@/interfaces'

export default defineComponent({
  name: 'App',
  components: {
    ConnectHeader,
    ConnectSystemBanner,
    ConnectFooter
  },
  setup () {
    const route = useRoute()
    const router = useRouter()
    const { goToDash, navigateToUrl } = useNavigation()
    const { isAuthenticated, loadAccountProductSubscriptions, initializeUserProducts, loadPaymentInfo } = useAuth()
    const {
      // Actions
      setRoleSbc,
      setUserInfo,
      setAuthRoles,
      setRegistrationNumber,
      setAccountInformation
    } = useStore()
    const {
      // Getters
      isRoleStaff,
      isRoleStaffBcol,
      isRoleStaffReg,
      hasPprEnabled,
      hasMhrEnabled,
      getAccountId,
      getUserEmail,
      getUserFirstName,
      getUserLastName,
      getUserRoles,
      getUserUsername,
      hasUnsavedChanges,
      getRegistrationType,
      getRegistrationOther,
      getRegistrationFlowType,
      getUserProductSubscriptionsCodes
    } = storeToRefs(useStore())
    const { $keycloak } = useNuxtApp()
    const { initAlternatePaymentMethod } = useConnectFeeStore()

    const localState = reactive({
      errorDisplay: false,
      errorOptions: loginError as DialogOptionsIF,
      saveDraftExitToggle: false,
      payErrorDisplay: false,
      payErrorOptions: null as DialogOptionsIF,
      profileReady: false,
      appReady: null,
      haveData: false,
      loggedOut: false,
      tokenService: false,
      actionInProgress: false,
      registryUrl: computed((): string => {
        // if REGISTRY_URL does not exist this will return 'undefined'. Needs to be null or str
        const configRegistryUrl = sessionStorage.getItem('REGISTRY_URL')
        if (configRegistryUrl) return configRegistryUrl
        return null
      }),
      bannerText: computed((): string => {
        // if banner text does not exist this will return 'undefined'. Needs to be null or str
        const bannerText = getFeatureFlag('banner-text')
        if (bannerText.trim().length > 0) return bannerText
        return null
      }),
      aboutText: computed((): string => {
        return useRuntimeConfig().public.ABOUT_TEXT
      }),
      isProd: computed((): boolean => {
        const env = sessionStorage.getItem('POD_NAMESPACE')
        if (env != null && env.trim().length > 0) {
          return Boolean(env.toLowerCase().endsWith('prod'))
        }
        return Boolean(false)
      }),
      registrationTypeUI: computed((): string => {
        const regType = getRegistrationType.value
        const regOther = getRegistrationOther.value
        if (regType?.registrationTypeAPI === APIRegistrationTypes.OTHER) {
          return regOther || ''
        }
        return regType?.registrationTypeUI || ''
      })
    })

    onBeforeMount((): void => {
      if (route?.query?.logout) {
        localState.loggedOut = true
        sessionStorage.removeItem(SessionStorageKeys.KeyCloakToken)
        router.push(`${window.location.origin}`)
      } else {
        localState.loggedOut = false
        // before unloading this page, if there are changes then prompt user
        window.onbeforeunload = (event) => {
          const changeRoutes = [
            RouteNames.RENEW_REGISTRATION,
            RouteNames.CONFIRM_RENEWAL,
            RouteNames.REVIEW_DISCHARGE,
            RouteNames.CONFIRM_DISCHARGE
          ]
          const newAmendRoutes = [
            RouteNames.AMEND_REGISTRATION,
            RouteNames.CONFIRM_AMENDMENT,
            RouteNames.LENGTH_TRUST,
            RouteNames.ADD_SECUREDPARTIES_AND_DEBTORS,
            RouteNames.ADD_COLLATERAL,
            RouteNames.REVIEW_CONFIRM
          ]
          const mhrRoutes = [
            RouteNames.YOUR_HOME,
            RouteNames.SUBMITTING_PARTY,
            RouteNames.HOME_OWNERS,
            RouteNames.HOME_LOCATION,
            RouteNames.MHR_REVIEW_CONFIRM,
            RouteNames.MHR_INFORMATION,
            RouteNames.MHRSEARCH,
            RouteNames.MHRSEARCH_CONFIRM
          ]

          const routeName = router.currentRoute.name as RouteNames
          if (
            (changeRoutes.includes(routeName) || newAmendRoutes.includes(routeName) || mhrRoutes.includes(routeName)) &&
            hasUnsavedChanges.value) {
            // browser popup
            event.preventDefault()
            // NB: custom text is no longer supported in any major browsers due to security reasons.
            // 'event.returnValue' is treated as a flag
            event.returnValue = 'You have unsaved changes. Are you sure you want to leave?'
          }
        }

        authVerificationHandler()
      }
    })

    /**
     * When we are authenticated, allow time for session storage propagation from auth, then initialize application
     * (since we won't get the event from signin component)
     */
    const authVerificationHandler = () => {
      // Set account and token to session
      const currentAccount = JSON.parse(sessionStorage.getItem('connect-core-account-store'))?.currentAccount
      sessionStorage.setItem('CURRENT_ACCOUNT', JSON.stringify(currentAccount))
      sessionStorage.setItem('KEYCLOAK_TOKEN', $keycloak.token)

      //
      setTimeout(() => {
        isAuthenticated.value && !!sessionStorage.getItem(SessionStorageKeys.CurrentAccount)
          ? onProfileReady(true)
          : authVerificationHandler()
      }, 2000)
    }

    const payErrorDialogHandler = (confirmed: boolean) => {
      const flowType = getRegistrationFlowType.value
      localState.payErrorDisplay = false
      if (confirmed) {
        if ([RegistrationFlowType.NEW, RegistrationFlowType.AMENDMENT].includes(flowType)) {
          localState.saveDraftExitToggle = !localState.saveDraftExitToggle
        } else {
          setRegistrationNumber(null)
          goToDash()
        }
      }
    }

    /** Initializes application. Also called for retry. */
    const initApp = async (): Promise<void> => {
      // reset errors in case of retry
      resetFlags()

      // ensure user is authorized for this profile
      const authResp = await loadAuth()
      if (authResp.statusCode !== StatusCodes.OK) {
        console.error(authResp.message)
        handleError(authResp)
        // show stopper so return
        return
      }

      // load user info
      const userInfoResp = await loadUserInfo()
      if (userInfoResp.statusCode !== StatusCodes.OK) {
        console.error(userInfoResp.message)
        handleError(userInfoResp)
        // show stopper so return
        return
      }

      try {
        await loadAccountProductSubscriptions()
      } catch (error) {
        console.error('Auth product subscription error = ', error)
      }

      if (getFeatureFlag('mhr-credit-card-enabled')) {
        try {
          await loadPaymentInfo()
        } catch (error) {
          console.error('Fetch payment information error = ', error)
        }
      }

      // update Launch Darkly
      try {
        await updateLaunchDarkly()
      } catch (error) {
        // just log the error -- no need to halt app
        console.error('Launch Darkly update error = ', error)
      }

      if (!isRoleStaff.value && !isRoleStaffReg.value && !isRoleStaffBcol.value && !hasPprEnabled.value &&
        !hasMhrEnabled.value) {
        handleError({
          category: ErrorCategories.PRODUCT_ACCESS,
          message: '',
          statusCode: StatusCodes.UNAUTHORIZED
        })
        return
      }

      // finally, let router views know they can load their data
      localState.appReady = true
    }

    /** Resets all error flags/states. */
    const resetFlags = (): void => {
      localState.appReady = false
      localState.haveData = false
      localState.errorDisplay = false
      localState.payErrorDisplay = false
    }

    /** Fetches authorizations and verifies and stores roles. */
    const loadAuth = async (): Promise<ErrorIF> => {
      // save roles from the keycloak token
      let message = ''
      let statusCode = StatusCodes.OK
      try {
        const authRoles = getKeycloakRoles()
        if (authRoles && authRoles.length > 0) {
          if (authRoles.includes('gov_account_user')) {
            // if staff make call to check for sbc
            const isSbc = await getSbcFromAuth()
            setRoleSbc(isSbc)
            isSbc && authRoles.push('sbc')
          }
          if (!authRoles.includes('ppr') && !authRoles.includes('mhr')) {
            throw new Error('No access to Assets')
          }
          setAuthRoles(authRoles)
        } else {
          throw new Error('Invalid auth roles')
        }
      } catch (error) {
        message = String(error)
        statusCode = StatusCodes.UNAUTHORIZED
      }

      return {
        category: ErrorCategories.ACCOUNT_ACCESS,
        message,
        statusCode
      }
    }

    /** Fetches current user info and stores it. */
    const loadUserInfo = async (): Promise<ErrorIF> => {
      // auth api user info
      const response = await fetchCurrentUser()
      let message = ''
      let statusCode = response.status
      const userInfo: UserInfoIF = response?.data
      if (userInfo && statusCode === StatusCodes.OK) {
        // set ppr api user settings
        const settings: UserSettingsIF = await getPPRUserSettings()
        userInfo.settings = settings
        if (settings?.error) {
          message = 'Unable to get user settings.'
          statusCode = settings.error.statusCode
        } else if (!isRoleStaff.value) {
          // check if non-billable
          userInfo.feeSettings = null
          const fees = await getFees(FeeCodes.SEARCH)
          if (fees.error) {
            message = 'Unable to check if user is non billable.'
            statusCode = fees.error.statusCode
          } else if (fees?.filingFees === 0) {
            userInfo.feeSettings = {
              isNonBillable: true,
              serviceFee: fees?.serviceFees || 1.50
            }
          }
        }
        setUserInfo(userInfo)

        if (getAccountId.value) {
          await initializeUserProducts()
        }
      } else {
        message = 'Unable to get user info.'
      }
      const resp: ErrorIF = {
        category: ErrorCategories.ACCOUNT_SETTINGS,
        message,
        statusCode
      }
      return resp
    }

    /**
     * Fetches current user data.
     * @returns a promise to return the user data
     */
    const fetchCurrentUser = (): Promise<any> => {
      const authUrl = sessionStorage.getItem('AUTH_API_URL')
      const config = { baseURL: authUrl }
      return axios.get('users/@me', config)
    }

    /** Gets user products and sets browser title accordingly. */
    const setBrowserTitle = (): void => {
      const userProducts = Array.from(getUserProductSubscriptionsCodes.value) as ProductCode[]
      if (userProducts.includes(ProductCode.PPR) &&
        userProducts.includes(ProductCode.MHR)) {
        document.title = 'BC Asset Registries (MHR/PPR)'
      } else if (userProducts.includes(ProductCode.MHR)) {
        document.title = 'BC Manufactured Home Registry'
      }
    }

    /** Gets account information (e.g. Premium account) and stores it. */
    const loadAccountInformation = (): void => {
      const currentAccount = sessionStorage.getItem(SessionStorageKeys.CurrentAccount)
      if (currentAccount) {
        const accountInfo = JSON.parse(currentAccount)
        setAccountInformation(accountInfo)
      }
    }

    /** Updates Launch Darkly with user info. */
    const updateLaunchDarkly = async (): Promise<any> => {
      // since username is unique, use it as the user key
      const key: string = getUserUsername.value as string
      const email: string = getUserEmail.value as string
      const firstName: string = getUserFirstName.value as string
      const lastName: string = getUserLastName.value as string
      // remove leading { and trailing } and tokenize string
      const custom: any = { roles: getUserRoles.value }

      await updateLdUser(key, email, firstName, lastName, custom)
    }

    const handleError = (error: ErrorIF): void => {
      localState.appReady = null
      switch (error?.category) {
        case ErrorCategories.ACCOUNT_ACCESS:
          localState.errorOptions = authPprError
          localState.errorDisplay = true
          break
        case ErrorCategories.ACCOUNT_SETTINGS:
          localState.errorOptions = loginError
          localState.errorDisplay = true
          break
        case ErrorCategories.DRAFT_DELETE:
          localState.errorOptions = draftDeleteError
          localState.errorDisplay = true
          break
        case ErrorCategories.DRAFT_LOAD:
          localState.errorOptions = registrationOpenDraftError
          localState.errorDisplay = true
          break
        case ErrorCategories.HISTORY_REGISTRATIONS:
          localState.errorOptions = historyRegError
          localState.errorDisplay = true
          break
        case ErrorCategories.HISTORY_SEARCHES:
          // handled inline
          break
        case ErrorCategories.PRODUCT_ACCESS:
          localState.errorOptions = authAssetsError
          localState.errorDisplay = true
          break
        case ErrorCategories.ADMIN_REGISTRATION:
          localState.errorOptions = registrationCompleteError
          localState.errorDisplay = true
          break
        case ErrorCategories.REGISTRATION_TRANSFER:
        case ErrorCategories.REGISTRATION_CREATE:
          handleErrorRegCreate(error)
          break
        case ErrorCategories.REGISTRATION_DELETE:
          localState.errorOptions = registrationDeleteError
          localState.errorDisplay = true
          break
        case ErrorCategories.REGISTRATION_LOAD:
          localState.errorOptions = registrationLoadError
          localState.errorDisplay = true
          goToDash()
          break
        case ErrorCategories.REGISTRATION_SAVE:
          localState.errorOptions = registrationSaveDraftError
          localState.errorDisplay = true
          break
        case ErrorCategories.REPORT_GENERATION:
          localState.errorOptions = openDocError
          localState.errorDisplay = true
          break
        case ErrorCategories.MHR_UNIT_NOTE_FILING:
          localState.errorOptions = unitNoteFilingError
          localState.errorDisplay = true
          break
        case ErrorCategories.SEARCH:
          handleErrorSearch(error)
          break
        case ErrorCategories.EXEMPTION_SAVE:
          localState.errorOptions = exemptionSaveError
          localState.errorDisplay = true
          break
        case ErrorCategories.TRANSPORT_PERMIT_FILING:
          localState.errorOptions = transportPermitFilingError
          localState.errorDisplay = true
          break
        case ErrorCategories.SEARCH_COMPLETE:
          // handled in search comp
          break
        case ErrorCategories.SEARCH_UPDATE:
          // handled in search comp
          break
        default:
          console.error('Unhandled error: ', error)
      }
    }

    const handleErrorRegCreate = (error: ErrorIF) => {
      // prep for registration payment issues
      let filing = localState.registrationTypeUI
      const flowType = getRegistrationFlowType.value as RegistrationFlowType

      if (flowType !== RegistrationFlowType.NEW) {
        filing = flowType?.toLowerCase() || 'registration'
      }
      localState.payErrorOptions = { ...paymentErrorReg }
      if (localState.registrationTypeUI) {
        localState.payErrorOptions.text = localState.payErrorOptions.text.replace('filing_type', filing)
      }
      // errors with a 'type' are payment issues, other errors handles in 'default' logic
      switch (error.type) {
        case (
          ErrorCodes.BCOL_ACCOUNT_CLOSED ||
          ErrorCodes.BCOL_USER_REVOKED ||
          ErrorCodes.BCOL_ACCOUNT_REVOKED ||
          ErrorCodes.BCOL_UNAVAILABLE
        ):
          // bcol expected errors
          if ([RegistrationFlowType.NEW, RegistrationFlowType.AMENDMENT].includes(flowType)) {
            localState.payErrorOptions.text += '<br/><br/>' + error.detail +
              `<br/><br/>Your ${filing} will be saved as a draft and you can retry your payment ` +
              'once the issue has been resolved.'
          } else {
            localState.payErrorOptions.acceptText = 'Return to Dashboard'
            localState.payErrorOptions.text += '<br/><br/>' + error.detail +
              'You can retry your payment once the issue has been resolved.'
          }
          localState.payErrorDisplay = true
          break
        case ErrorCodes.ACCOUNT_IN_PAD_CONFIRMATION_PERIOD:
          // pad expected errors
          localState.payErrorOptions.text += '<br/><br/>' + error.detail +
            '<br/><br/>If this error continues after the waiting period has completed, please contact us.'
          localState.payErrorOptions.hasContactInfo = true
          localState.payErrorDisplay = true
          break
        default:
          if (error.type && error.type?.includes('BCOL') && error.detail) {
            // generic catch all bcol
            if ([RegistrationFlowType.NEW, RegistrationFlowType.AMENDMENT].includes(flowType)) {
              localState.payErrorOptions.text += '<br/><br/>' + error.detail +
                `<br/><br/>Your ${filing} will be saved as a draft and you can retry your payment ` +
                'once the issue has been resolved.'
            } else {
              localState.payErrorOptions.acceptText = 'Return to Dashboard'
              localState.payErrorOptions.text += '<br/><br/>' + error.detail +
                'You can retry your payment once the issue has been resolved.'
            }
            localState.payErrorDisplay = true
          } else if (error.statusCode === StatusCodes.PAYMENT_REQUIRED) {
            // generic catch all pay error
            const errorDetail = error.type ? error.detail : parsePayDetail(error.detail)
            localState.payErrorOptions.text = `The payment could not be completed at this time for the following
              reason:<br/><br/><b>${errorDetail}</b><br/><br/>If this issue persists, please contact us.`
            localState.payErrorOptions.hasContactInfo = true
            localState.payErrorDisplay = true
          } else {
            localState.errorOptions = registrationCompleteError
            localState.errorDisplay = true
          }
      }
    }

    const handleErrorSearch = (error: ErrorIF) => {
      switch (error.type) {
        case (
          ErrorCodes.BCOL_ACCOUNT_CLOSED ||
          ErrorCodes.BCOL_USER_REVOKED ||
          ErrorCodes.BCOL_ACCOUNT_REVOKED ||
          ErrorCodes.BCOL_UNAVAILABLE
        ):
          localState.payErrorOptions = { ...paymentErrorSearch }
          localState.payErrorOptions.text += '<br/><br/>' + error.detail
          localState.payErrorDisplay = true
          break
        case ErrorCodes.ACCOUNT_IN_PAD_CONFIRMATION_PERIOD:
          localState.payErrorOptions = { ...paymentErrorSearch }
          localState.payErrorOptions.text += '<br/><br/>' + error.detail +
            '<br/><br/>If this error continues after the waiting period has completed, please contact us.'
          localState.payErrorOptions.hasContactInfo = true
          localState.payErrorDisplay = true
          break
        default:
          if (error.type && error.type?.includes('BCOL') && error.detail) {
            // bcol generic
            localState.payErrorOptions = { ...paymentErrorSearch }
            localState.payErrorOptions.text += '<br/><br/>' + error.detail
            localState.payErrorDisplay = true
          } else if (error.statusCode === StatusCodes.PAYMENT_REQUIRED) {
            // generic pay error
            localState.payErrorOptions = { ...paymentErrorSearch }
            localState.payErrorOptions.text = '<b>The payment could not be completed at this time</b>' +
              '<br/><br/>If this issue persists, please contact us.'
            localState.payErrorOptions.hasContactInfo = true
            localState.payErrorDisplay = true
          } else {
            // generic search error
            localState.errorOptions = { ...searchResultsError }
            localState.errorDisplay = true
          }
      }
    }

    const proceedAfterError = (proceed: boolean): void => {
      localState.errorDisplay = false
      // Navigate to Registries dashboard in the event of a login or access error.
      if ([loginError.title, authPprError.title, authAssetsError.title].includes(localState.errorOptions.title)) {
        navigateToUrl(localState.registryUrl)
      }
      // for now just refresh app
      if (!proceed) initApp()
    }

    const onProfileReady = async (val: boolean): Promise<void> => {
      if (val && !localState.loggedOut) {
        // load account information
        loadAccountInformation()

        // initialize app
        await initApp()

        // initialize payment options
        if (!isRoleStaff.value) await initAlternatePaymentMethod()

        // set browser title
        setBrowserTitle()
      }
    }

    // Set up an interval to sync the session token
    setInterval(async () => {
      try {
        // Token was refreshed, update your session storage or state as needed
        sessionStorage.setItem('KEYCLOAK_TOKEN', await useKeycloak().getToken())
      } catch (err) {
        // Handle error, possibly force logout
        console.error('Token sync failed', err)
      }
    }, 2 * 60 * 1000) // every 2 minutes

    /** Called when profile is ready -- we can now init app. */
    watch(() => localState.profileReady, async (val: boolean) => {
      await onProfileReady(val)
    })

    return {
      handleError,
      proceedAfterError,
      payErrorDialogHandler,
      ...toRefs(localState)
    }
  }
})
</script>
<template>
  <!-- To provide tooltip context, UApp needs to be added. -->
  <UApp>
    <v-app
      id="app"
      class="app-container"
    >
      <SkipToMainContent main-content-id="main-content" />

      <!-- Dialogs -->
      <BaseDialog
        id="errorDialogApp"
        :set-display="errorDisplay"
        :set-options="errorOptions"
        @proceed="proceedAfterError"
      />
      <BaseDialog
        id="payErrorDialogApp"
        :set-display="payErrorDisplay"
        :set-options="payErrorOptions"
        @proceed="payErrorDialogHandler($event)"
      />
      <!-- Application Header -->
      <connect-header />
      <connect-system-banner />

      <nav v-if="haveData">
        <Breadcrumb />
      </nav>

      <div class="app-body">
        <main
          id="main-content"
          tabindex="-1"
        >
          <Tombstone
            v-if="haveData"
            :action-in-progress="actionInProgress"
          />
          <v-container class="py-0">
            <v-row no-gutters>
              <v-col cols="12">
                <NuxtPage
                  :app-loading-data="!haveData"
                  :app-ready="appReady"
                  :save-draft-exit="saveDraftExitToggle"
                  :registry-url="registryUrl"
                  @profile-ready="profileReady = true"
                  @error="handleError($event)"
                  @have-data="haveData = $event"
                  @action-in-progress="actionInProgress = $event"
                />
              </v-col>
            </v-row>
          </v-container>
        </main>
      </div>

       <connect-footer />
    </v-app>
  </UApp>
</template>

<style lang="scss">
@import '@/assets/styles/theme';
@import '@/assets/styles/overrides';
</style>
