<template>
  <div class="base-address">
    <!-- Display fields -->
    <v-expand-transition>
      <div
        v-if="!editing"
        class="address-block"
      >
        <div class="address-block__info pre-wrap">
          <p class="address-block__info-row">
            {{ addressLocal.street }}
          </p>
          <p
            v-if="addressLocal.streetAdditional"
            class="address-block__info-row"
          >
            {{ addressLocal.streetAdditional }}
          </p>
          <p class="address-block__info-row">
            <span>{{ addressLocal.city }}</span>
            <span v-if="addressLocal.region">&nbsp;{{ addressLocal.region }}&nbsp;</span>
            <span v-if="addressLocal.postalCode">&nbsp;{{ addressLocal.postalCode }}</span>
          </p>
          <p class="address-block__info-row">
            {{ getCountryName(country) }}
          </p>
          <p
            v-if="addressLocal.deliveryInstructions"
            class="address-block__info-row delivery-text"
          >
            {{ addressLocal.deliveryInstructions }}
          </p>
        </div>
      </div>
    </v-expand-transition>

    <!-- Edit fields -->
    <v-expand-transition>
      <v-form
        v-if="editing"
        ref="addressForm"
        name="address-form"
        lazy-validation
      >
        <div class="form__row">
          <v-autocomplete
            v-model="addressLocal.country"
            autocomplete="new-password"
            variant="filled"
            color="primary"
            class="address-country"
            hide-no-data
            item-title="name"
            item-value="code"
            :disabled="disableEdits"
            :items="getCountries()"
            :label="countryLabel"
            :rules="[...schemaLocal.country]"
          >
            <template #item="{item, props}">
              <v-divider v-if="item.raw.divider" />
              <v-list-item
                v-else
                v-bind="props"
              />
            </template>
          </v-autocomplete>
          <!--special field to select AddressComplete country, separate from our model field-->
          <input
            :id="countryId"
            type="hidden"
            :value="country"
          >
        </div>
        <div class="form__row">
          <!-- NB1: AddressComplete needs to be enabled each time user clicks in this search field.
               NB2: Only process first keypress -- assumes if user moves between instances of this
                   component then they are using the mouse (and thus, clicking). -->
          <v-text-field
            :id="streetId"
            v-model="addressLocal.street"
            autocomplete="new-password"
            class="street-address"
            variant="filled"
            color="primary"
            :disabled="disableEdits"
            :hint="hideAddressHint ? '' : 'Street address, PO box, rural route, or general delivery address'"
            :label="streetLabel"
            persistent-hint
            :rules="[...schemaLocal.street]"
            @keypress.once="enableAddressComplete()"
            @click="enableAddressComplete()"
          />
        </div>
        <div class="form__row">
          <v-textarea
            v-model="addressLocal.streetAdditional"
            autocomplete="new-password"
            auto-grow
            variant="filled"
            color="primary"
            class="street-address-additional"
            :disabled="disableEdits"
            :label="streetAdditionalLabel"
            rows="1"
            :rules="!!addressLocal.streetAdditional ? [...schemaLocal.streetAdditional] : []"
          />
        </div>
        <div class="form__row three-column">
          <v-text-field
            v-model="addressLocal.city"
            autocomplete="new-password"
            variant="filled"
            color="primary"
            class="item address-city"
            :disabled="disableEdits"
            :label="cityLabel"
            :rules="[...schemaLocal.city]"
          />
          <v-autocomplete
            v-if="useCountryRegions(country)"
            v-model="addressLocal.region"
            autocomplete="new-password"
            variant="filled"
            color="primary"
            class="item address-region"
            hide-no-data
            item-title="name"
            item-value="short"
            :disabled="disableEdits"
            :items="getCountryRegions(country)"
            :label="regionLabel"
            :rules="[...schemaLocal.region]"
          >
            <template #item="{item, props}">
              <v-divider v-if="item.raw.divider" />
              <v-list-item
                v-else
                v-bind="props"
              />
            </template>
          </v-autocomplete>
          <v-text-field
            v-else
            v-model="addressLocal.region"
            variant="filled"
            color="primary"
            class="item address-region"
            :disabled="disableEdits"
            :label="regionLabel"
            :rules="[...schemaLocal.region]"
          />
          <v-text-field
            v-model="addressLocal.postalCode"
            variant="filled"
            color="primary"
            class="item postal-code"
            :disabled="disableEdits"
            :label="postalCodeLabel"
            :rules="[...schemaLocal.postalCode]"
          />
        </div>
        <div
          v-if="!hideDeliveryAddress"
          class="form__row"
        >
          <v-textarea
            v-model="addressLocal.deliveryInstructions"
            auto-grow
            variant="filled"
            color="primary"
            class="delivery-instructions"
            :disabled="disableEdits"
            :label="deliveryInstructionsLabel"
            rows="2"
            :rules="!!addressLocal.deliveryInstructions ? [...schemaLocal.deliveryInstructions] : []"
          />
        </div>
      </v-form>
    </v-expand-transition>
  </div>
</template>

<script lang="ts">
import { defineComponent, onMounted, watch, toRef, computed } from 'vue'
import {
  baseRules,
  useAddress,
  useAddressComplete,
  useCountryRegions,
  useCountriesProvinces,
  useBaseValidations,
  spaceRules
} from '@/composables/address/factories'
import type { AddressIF, SchemaIF } from '@/composables/address/interfaces'

export default defineComponent({
  name: 'BaseAddress',
  props: {
    value: {
      type: Object as () => AddressIF,
      default: () => ({
        street: '',
        streetAdditional: '',
        city: '',
        region: null,
        postalCode: '',
        country: null,
        deliveryInstructions: ''
      })
    },
    /* used for readonly mode vs edit mode */
    editing: {
      type: Boolean,
      default: false
    },
    /* contains validation for each field */
    schema: {
      type: Object as () => SchemaIF,
      default: null
    },
    /* triggers all current form validation errors */
    triggerErrors: {
      type: Boolean,
      default: false
    },
    /* Hides the persistent hint field on Address Input */
    hideAddressHint: {
      type: Boolean,
      default: false
    },
    /* Hides Delivery Address field (e.g. for Unit Notes) */
    hideDeliveryAddress: {
      type: Boolean,
      default: false
    },
    disableEdits: {
      type: Boolean,
      default: false
    }
  },
  emits: ['valid', 'updateAddress'],
  setup (props, { emit }) {
    const addressProp = computed((): AddressIF => {
      return props.value
    })
    const localSchema = { ...props.schema }
    const {
      addressLocal,
      country,
      schemaLocal,
      isSchemaRequired,
      labels
    } = useAddress(toRef(addressProp), localSchema)
    const origPostalCodeRules = localSchema.postalCode
    const origRegionRules = localSchema.region
    const origCityRules = localSchema.city

    const { addressForm, validate } = useBaseValidations()

    const { enableAddressComplete, uniqueIds } = useAddressComplete(addressLocal)

    const countryProvincesHelpers = useCountriesProvinces()

    const countryChangeHandler = (val: string, clearAddress: boolean) => {
      // do not trigger any changes if it is view only (summary instance)
      if (!props.editing) return

      if (val === 'CA') {
        localSchema.postalCode = origPostalCodeRules.concat([baseRules.postalCode])
        localSchema.region = origRegionRules
        localSchema.city = origCityRules
      } else if (val === 'US') {
        localSchema.postalCode = origPostalCodeRules.concat([baseRules.zipCode])
        localSchema.region = origRegionRules
        localSchema.city = origCityRules
      } else {
        // Convert to optional rules for non-CA/US countries
        localSchema.postalCode = [baseRules.maxLength(15), ...spaceRules]
        localSchema.region = [baseRules.maxLength(2), ...spaceRules]
        localSchema.city = [baseRules.maxLength(40), ...spaceRules]
      }
      // reset other address fields (check is for loading an existing address)
      if (clearAddress) {
        addressLocal.value.street = ''
        addressLocal.value.streetAdditional = ''
        addressLocal.value.city = ''
        addressLocal.value.region = ''
        addressLocal.value.postalCode = ''
      }
      // wait for schema update and validate the form
      setTimeout(() => {
        props.triggerErrors && validate()
      }, 5)
    }

    /** Return TRUE when the provided region belongs to the provided country **/
    const isRegionMatch = (country: string, region: string): boolean => {
      return useCountriesProvinces().getCountryRegions(country)?.some(regionObj => {
        return regionObj?.short === region
      })
    }

    onMounted(() => {
      countryChangeHandler(addressLocal.value.country, false)
    })

    watch(() => addressLocal.value, (val) => {
      let valid = true
      /** checks each field against the schema rules to see if the address is valid or not
       * NOTE: we don't want it to trigger error msgs yet which is why this does not call validate()
      */
      for (const key in val) {
        for (const index in schemaLocal.value[key]) {
          if (schemaLocal.value[key][index](val[key]) !== true) {
            valid = false
            break
          }
        }
        if (!valid) break
      }
      emit('valid', valid)
      emit('updateAddress', val)
    }, { immediate: true, deep: true })

    watch(() => country.value, (val) => {
      countryChangeHandler(val, !isRegionMatch(country.value, addressLocal.value.region))
    })

    watch(() => props.triggerErrors, () => {
      validate()
    })

    return {
      addressForm,
      addressLocal,
      country,
      ...countryProvincesHelpers,
      enableAddressComplete,
      isSchemaRequired,
      ...labels,
      schemaLocal,
      useCountryRegions,
      ...uniqueIds,
      validate
    }
  }
})
</script>

<style lang="scss" scoped>
@import '@/assets/styles/theme.scss';

.delivery-text {
  font-style: italic;
  margin-top: 10px;
}

// Address Block Layout
.address-block {
  display: flex;
  p {
    margin-bottom: unset;
  }
}

.address-block__info {
  flex: 1 1 auto;
}

// Form Row Elements
.form__row {
  margin-top: 12px;
}
.form__row.three-column {
  align-items: stretch;
  display: flex;
  flex-flow: row nowrap;
  margin-left: -0.5rem;
  margin-right: -0.5rem;

  .item {
    flex: 1 1 auto;
    flex-basis: 0;
    margin-left: 0.5rem;
    margin-right: 0.5rem;
  }
}

.pre-wrap {
  white-space: pre-wrap;
}

// make 'readonly' inputs looks disabled
// (can't use 'disabled' because we want normal error styling)
.v-select.v-input--is-readonly,
.v-text-field.v-input--is-readonly {
  pointer-events: none;

  :deep(.v-label) {
    // set label colour to same as disabled
    color: rgba(0,0,0,.38);
  }

  :deep(.v-select__selection) {
    // set selection colour to same as disabled
    color: rgba(0,0,0,.38);
  }

  :deep(.v-icon) {
    // set error icon colour to same as disabled
    color: rgba(0,0,0,.38) !important;
    opacity: 0.6;
  }
}
</style>
