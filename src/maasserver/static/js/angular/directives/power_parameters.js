/* Copyright 2015 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Power parameters directive.
 */

angular.module('MAAS').run(['$templateCache', function ($templateCache) {
    // Inject the power-parameters.html into the template cache.
    $templateCache.put('directive/templates/power-parameters.html', [
        '<div class="inline">',
            '<label for="power-type">Power type</label>',
            '<select name="power-type" id="power-type" ',
                'placeholder="Choose a power type" ',
                'data-ng-model="ngModel.type" ',
                'data-ng-options="',
                'type as type.description for type in maasPowerParameters">',
                '<option value="" disabled selected>',
                    'Select your power type',
                '</option>',
            '</select>',
        '</div>',
        '<div class="inline" data-ng-repeat="field in ngModel.type.fields">',
            '<label for="{$ field.name $}">{$ field.label $}</label>',
            '<maas-power-input field="field" ',
                'data-ng-model="ngModel.parameters[field.name]">',
        '</div>'
    ].join(''));
}]);

angular.module('MAAS').directive('maasPowerInput', ['$compile',
    function($compile) {
        return {
            restrict: "E",
            require: "ngModel",
            scope: {
                field: '=',
                ngModel: '='
            },
            link: function(scope, element, attrs) {
                var type = scope.field.field_type;
                var req = scope.field.required ? 'required="required" ' : '';
                var html = "";
                if(type === "string" || type === "mac_address") {
                    // Build an input element with the correct attributes.
                    html =
                        '<input type="text" name="' + scope.field.name + '" ' +
                        req + 'data-ng-model="' + attrs.ngModel + '" ';

                    // Add mac address validation.
                    if(type === "mac_address") {
                        html +=
                            'data-ng-pattern="' +
                            '/^([0-9A-Fa-f]{2}:){5}([0-9A-Fa-f]{2})$/"';
                    }
                    html += '>';

                    // Set the default value for the input on the model.
                    if(!angular.isObject(scope.ngModel)) {
                        scope.ngModel = scope.field["default"];
                    }
                } else if(type === "choice") {
                    // Build a select element with the correct attributes.
                    html =
                        '<select name="' + scope.field.name + '"' +
                        req + 'data-ng-model="' + attrs.ngModel + '" ' +
                        'data-ng-options="' +
                        'choice as choice[1] for choice in field.choices' +
                        '">';
                    html += '</select>';

                    // Set the default choice on the model.
                    if(!angular.isObject(scope.ngModel)) {
                        var i;
                        for(i = 0; i < scope.field.choices.length; i++) {
                            var choice = scope.field.choices[i];
                            if(scope.field["default"] === choice[0]) {
                                scope.ngModel = choice;
                                break;
                            }
                        }
                    }
                } else {
                    throw new Error("Unknown power_type: "+ type);
                }

                // Replace the element with the compiled html using the parents
                // scope. The parent scope is used because we want to build the
                // element as if it was in the parent scope, not the scope that
                // is defined in this directive.
                element.replaceWith($compile(html)(scope.$parent));
            }
        };
    }]);

angular.module('MAAS').directive('maasPowerParameters', function() {
    return {
        restrict: "A",
        require: "ngModel",
        scope: {
            maasPowerParameters: '=',
            ngModel: '='
        },
        templateUrl: 'directive/templates/power-parameters.html'
    };
});
